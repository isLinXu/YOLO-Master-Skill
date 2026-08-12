from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.cli.contract import (
    _atomic_write_json,
    ensure_manifest_dir,
    json_safe,
    redact_sensitive,
    response,
    write_manifest,
)
from runtime.paths import SKILL_ROOT, YOLO_MASTER_ROOT


DISPATCHER = SKILL_ROOT / "scripts" / "run_yolo_master_skill.py"
JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}
SUCCESSFUL_RESPONSE_STATUSES = {"ok", "partial"}


class JobCancelled(Exception):
    """Signal that the local runner should stop its child process."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def async_requested(request: dict[str, Any]) -> bool:
    value = request.get("policy", {}).get("async")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, redact_sensitive(json_safe(payload)))


def _last_json_line(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _redact_log_file(path: Path) -> None:
    """Sanitize persisted child output after it has been closed by the runner."""
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        redacted = redact_sensitive(content)
        if redacted != content:
            path.write_text(redacted, encoding="utf-8")
    except OSError:
        return


class AsyncJobManager:
    """Manage local, file-backed asynchronous skill jobs with durable terminal state."""

    def __init__(self, root: Path | None = None):
        self.root = root

    def _jobs_dir(self) -> Path:
        base = self.root or SKILL_ROOT / "logs" / "async-jobs"
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        text = str(job_id)
        if not JOB_ID_RE.fullmatch(text):
            raise ValueError(
                "`job_id` must be a 12-character lowercase hexadecimal identifier."
            )
        return text

    def _job_dir(self, job_id: str, *, create: bool = False) -> Path:
        safe_job_id = self._validate_job_id(job_id)
        path = self._jobs_dir() / safe_job_id
        if create:
            path.mkdir(parents=True, exist_ok=False)
        return path

    @staticmethod
    def _status_path(job_dir: Path) -> Path:
        return job_dir / "status.json"

    def _read_status(self, job_dir: Path) -> dict[str, Any]:
        return _read_json(self._status_path(job_dir))

    def _write_status(self, job_dir: Path, status: dict[str, Any]) -> dict[str, Any]:
        _write_json(self._status_path(job_dir), status)
        return status

    @staticmethod
    def _runner_alive(pid: Any, job_dir: Path) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        if os.name == "nt":
            return True

        # PID liveness alone is not sufficient after a process exits: ensure this is our runner.
        try:
            process = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False
        command = process.stdout.strip()
        return (
            process.returncode == 0
            and "--run-job" in command
            and str(job_dir) in command
        )

    def submit(
        self, skill: str, request: dict[str, Any], callback_url: str | None = None
    ) -> dict[str, Any]:
        job_id = uuid4().hex[:12]
        child_request = redact_sensitive(json_safe(request))
        child_request["request_id"] = (
            f"{request.get('request_id', skill.replace('.', '-'))}-{job_id}"
        )
        policy = child_request.get("policy")
        child_request["policy"] = dict(policy) if isinstance(policy, dict) else {}
        child_request["policy"]["async"] = False
        child_request["policy"].pop("callback_url", None)
        runtime = child_request.get("runtime")
        if isinstance(runtime, dict):
            runtime.pop("callback_url", None)

        progress_path = ensure_manifest_dir(child_request) / "progress.jsonl"
        job_dir = self._job_dir(job_id, create=True)
        request_path = job_dir / "request.json"
        status_path = self._status_path(job_dir)
        stdout_path = job_dir / "stdout.jsonl"
        stderr_path = job_dir / "stderr.log"
        result_path = job_dir / "result.json"
        _write_json(request_path, child_request)
        status = {
            "job_id": job_id,
            "skill": skill,
            "status": "queued",
            "submitted_at": _timestamp(),
            "request_path": str(request_path),
            "result_path": str(result_path),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "progress_path": str(progress_path),
            "callback_configured": bool(callback_url),
        }
        self._write_status(job_dir, status)
        try:
            runner = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "runtime.cli.async_jobs",
                    "--run-job",
                    str(job_dir),
                    "--jobs-root",
                    str(self._jobs_dir()),
                ],
                cwd=SKILL_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            status.update(
                {
                    "status": "failed",
                    "completed_at": _timestamp(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            self._write_status(job_dir, status)
            raise

        current = self._read_status(job_dir)
        if current.get("status") == "queued" and not current.get("runner_pid"):
            current.update({"pid": runner.pid, "runner_pid": runner.pid})
            self._write_status(job_dir, current)
        else:
            current = self._read_status(job_dir)

        return {
            **current,
            "pid": runner.pid,
            "runner_pid": runner.pid,
            "status_path": str(status_path),
        }

    def status(self, job_id: str) -> dict[str, Any]:
        job_id = self._validate_job_id(job_id)
        job_dir = self._job_dir(job_id)
        status_path = self._status_path(job_dir)
        if not status_path.exists():
            return {"job_id": job_id, "status": "missing"}

        status = self._read_status(job_dir)
        if not status:
            return {
                "job_id": job_id,
                "status": "interrupted",
                "error": {
                    "type": "JobStateError",
                    "message": "job status file is unreadable",
                },
            }
        if status.get("status") in TERMINAL_JOB_STATUSES:
            return status

        runner_pid = status.get("runner_pid", status.get("pid"))
        if status.get("status") == "queued" and not isinstance(runner_pid, int):
            return status
        if self._runner_alive(runner_pid, job_dir):
            return status

        # Only the runner can attest success. A vanished non-terminal runner is interrupted, never completed.
        status.update(
            {
                "status": "interrupted",
                "completed_at": _timestamp(),
                "error": {
                    "type": "JobRunnerLost",
                    "message": "job runner exited before recording a terminal result",
                },
            }
        )
        return self._write_status(job_dir, status)

    def cancel(self, job_id: str) -> dict[str, Any]:
        status = self.status(job_id)
        if (
            status.get("status") in TERMINAL_JOB_STATUSES
            or status.get("status") == "missing"
        ):
            return {**status, "cancel_requested": False}

        job_dir = self._job_dir(str(status["job_id"]))
        status.update(
            {
                "status": "cancelling",
                "cancel_requested": True,
                "cancel_requested_at": _timestamp(),
            }
        )
        self._write_status(job_dir, status)
        runner_pid = status.get("runner_pid", status.get("pid"))
        if not isinstance(runner_pid, int):
            return status
        try:
            if os.name == "nt":
                os.kill(runner_pid, signal.SIGTERM)
            else:
                os.killpg(runner_pid, signal.SIGTERM)
        except OSError:
            updated = self.status(str(status["job_id"]))
            updated["cancel_requested"] = False
            return updated
        return status


def _terminate_child(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def _runner_status(job_dir: Path, **updates: Any) -> dict[str, Any]:
    status_path = job_dir / "status.json"
    status = _read_json(status_path)
    status.update(updates)
    _write_json(status_path, status)
    return status


def run_async_job(job_dir: Path) -> int:
    """Execute one request and durably record a terminal status for its submitted job."""
    job_dir = job_dir.resolve()
    request_path = job_dir / "request.json"
    stdout_path = job_dir / "stdout.jsonl"
    stderr_path = job_dir / "stderr.log"
    result_path = job_dir / "result.json"
    child: subprocess.Popen[str] | None = None

    def cancel_handler(_signum: int, _frame: Any) -> None:
        raise JobCancelled

    previous_term = signal.signal(signal.SIGTERM, cancel_handler)
    previous_int = signal.signal(signal.SIGINT, cancel_handler)
    try:
        status = _read_json(job_dir / "status.json")
        if status.get("status") in {"cancelled", "cancelling"}:
            _runner_status(
                job_dir,
                status="cancelled",
                completed_at=_timestamp(),
                cancelled_at=_timestamp(),
            )
            return 0
        _runner_status(
            job_dir,
            status="running",
            runner_pid=os.getpid(),
            pid=os.getpid(),
            started_at=_timestamp(),
        )

        request = _read_json(request_path)
        if not request:
            raise ValueError("job request file is unreadable")
        with (
            stdout_path.open("a", encoding="utf-8") as stdout,
            stderr_path.open("a", encoding="utf-8") as stderr,
        ):
            child = subprocess.Popen(
                [sys.executable, str(DISPATCHER), "--request", str(request_path)],
                cwd=YOLO_MASTER_ROOT,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            _runner_status(job_dir, child_pid=child.pid)
            exit_code = child.wait()

        _redact_log_file(stdout_path)
        _redact_log_file(stderr_path)
        payload = _last_json_line(stdout_path)
        result = {
            "job_id": status.get("job_id"),
            "exit_code": exit_code,
            "response_status": payload.get("status"),
            "response_summary": payload.get("summary"),
            "manifest_path": payload.get("manifest"),
            "response": payload,
        }
        _write_json(result_path, result)
        succeeded = (
            exit_code == 0 and payload.get("status") in SUCCESSFUL_RESPONSE_STATUSES
        )
        _runner_status(
            job_dir,
            status="succeeded" if succeeded else "failed",
            exit_code=exit_code,
            completed_at=_timestamp(),
            result_path=str(result_path),
            response_status=payload.get("status"),
            response_summary=payload.get("summary"),
            manifest_path=payload.get("manifest"),
        )
        return 0 if succeeded else 1
    except JobCancelled:
        if child is not None:
            _terminate_child(child)
        _runner_status(
            job_dir,
            status="cancelled",
            completed_at=_timestamp(),
            cancelled_at=_timestamp(),
        )
        return 0
    except Exception as exc:
        if child is not None:
            _terminate_child(child)
        _runner_status(
            job_dir,
            status="failed",
            completed_at=_timestamp(),
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def submit_async_skill(request: dict[str, Any]) -> dict[str, Any]:
    callback_url = request.get("policy", {}).get("callback_url") or request.get(
        "runtime", {}
    ).get("callback_url")
    job = AsyncJobManager().submit(
        str(request["skill"]), request, callback_url=callback_url
    )
    payload = response(
        request["skill"],
        "running",
        "asynchronous job submitted",
        job={
            "mode": "async",
            "job_id": job["job_id"],
            "pid": job["pid"],
            "status_path": job["status_path"],
            "result_path": job["result_path"],
            "progress_path": job["progress_path"],
            "stdout_path": job["stdout_path"],
            "stderr_path": job["stderr_path"],
            "callback_configured": job["callback_configured"],
        },
        next_actions=["yolo.job.status", "tail progress.jsonl"],
    )
    payload["manifest"] = str(write_manifest(request, payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Internal runner for YOLO-Master asynchronous jobs."
    )
    parser.add_argument("--run-job", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--jobs-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    jobs_root = (
        args.jobs_root.resolve()
        if args.jobs_root is not None
        else (SKILL_ROOT / "logs" / "async-jobs").resolve()
    )
    job_dir = args.run_job.resolve()
    if (
        not JOB_ID_RE.fullmatch(job_dir.name)
        or job_dir.parent != jobs_root
        or not job_dir.is_dir()
    ):
        parser.error("--run-job must reference a managed job directory.")
    return run_async_job(job_dir)


if __name__ == "__main__":
    raise SystemExit(main())
