from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.cli.contract import (
    ensure_manifest_child,
    ensure_manifest_dir,
    plan_response,
    response,
    write_manifest,
)
from runtime.cli.executor import (
    capture_output,
    cli_logs,
    cli_plan,
    ensure_cli_success,
    ensure_yolo_cli,
    isolated_cli_env,
    isolated_ultralytics_runs_dir,
    isolated_python_env,
    kv_arg,
)
from runtime.cli.normalize import is_dry_run, prefer_cli
from runtime.paths import SKILL_ROOT, YOLO_MASTER_ROOT

REPO_ROOT = YOLO_MASTER_ROOT
LOG_DIR = SKILL_ROOT / "logs"
MODULE_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class LauncherDeps:
    run_cli: Callable[..., dict[str, Any]]
    get_cfg_helpers: Callable[[], dict[str, Any]]
    ensure_yolo_cli: Callable[..., tuple[str, dict[str, Any]]] = ensure_yolo_cli
    repo_root: Path = REPO_ROOT
    log_dir: Path = LOG_DIR
    python_executable: str = sys.executable


def cached(name: str, loader: Callable[[], Any]) -> Any:
    if name not in MODULE_CACHE:
        MODULE_CACHE[name] = loader()
    return MODULE_CACHE[name]


def get_cfg_helpers() -> dict[str, Any]:
    def _loader():
        cfg = importlib.import_module("ultralytics.cfg")
        return {
            "DEFAULT_CFG_PATH": cfg.DEFAULT_CFG_PATH,
            "copy_default_cfg": cfg.copy_default_cfg,
            "handle_yolo_solutions": cfg.handle_yolo_solutions,
        }

    return cached("cfg_helpers", _loader)


def format_solution_arg(key: str, value: Any) -> str:
    if isinstance(value, str):
        return f"{key}={value}"
    return f"{key}={repr(value)}"


def run_solutions(request: dict[str, Any], deps: LauncherDeps) -> dict[str, Any]:
    solution = request["inputs"].get("solution")
    if not solution:
        raise ValueError("`inputs.solution` is required for yolo.solutions.run.")
    params = dict(request["params"])
    if solution == "crop" or "crop_dir" in params:
        params["crop_dir"] = str(
            ensure_manifest_child(
                request,
                params.get("crop_dir"),
                "params.crop_dir",
                "cropped-detections",
            )
        )
    artifact_dir = ensure_manifest_dir(request)
    if is_dry_run(request):
        if prefer_cli(request):
            args = ["solutions", solution]
            for key in ("model", "source"):
                if request["inputs"].get(key) is not None:
                    args.append(kv_arg(key, request["inputs"][key]))
            for key, value in params.items():
                if key != "action":
                    args.append(kv_arg(key, value))
            return cli_plan(request, args)
        args = [solution]
        for key in ("model", "source"):
            if request["inputs"].get(key) is not None:
                args.append(format_solution_arg(key, request["inputs"][key]))
        for key, value in params.items():
            if key != "action":
                args.append(format_solution_arg(key, value))
        return plan_response(
            request,
            "solutions dry run prepared",
            "module",
            "handle_yolo_solutions",
            params={"args": args},
        )

    if prefer_cli(request):
        args = ["solutions", solution]
        for key in ("model", "source"):
            if request["inputs"].get(key) is not None:
                args.append(kv_arg(key, request["inputs"][key]))
        for key, value in params.items():
            if key != "action":
                args.append(kv_arg(key, value))
        cli_result = deps.run_cli(
            args, cwd=artifact_dir, isolated_runs_dir=artifact_dir
        )
        failed = ensure_cli_success(request, cli_result, "solutions run failed")
        if failed:
            return failed
        return response(
            request["skill"],
            "ok",
            "solution run finished",
            logs=cli_logs(cli_result),
            artifacts=[
                {
                    "kind": "directory",
                    "path": str(artifact_dir.resolve()),
                }
            ],
        )

    with isolated_ultralytics_runs_dir(artifact_dir):
        _, stdout, stderr = capture_output(
            deps.get_cfg_helpers()["handle_yolo_solutions"],
            [
                solution,
                *[
                    format_solution_arg(k, v)
                    for k, v in request["inputs"].items()
                    if k != "solution"
                ],
                *[
                    format_solution_arg(k, v)
                    for k, v in params.items()
                    if k != "action"
                ],
            ],
        )
    payload = response(
        request["skill"],
        "ok",
        "solution run finished",
        logs={"stdout": stdout, "stderr": stderr},
        artifacts=[
            {
                "kind": "directory",
                "path": str(artifact_dir.resolve()),
            }
        ],
    )
    payload["manifest"] = str(write_manifest(request, payload))
    return payload


def run_ui_launch(request: dict[str, Any], deps: LauncherDeps) -> dict[str, Any]:
    mode = request["inputs"].get("mode") or request["params"].get("mode", "gradio")
    if is_dry_run(request):
        cmd_preview = (
            [deps.python_executable, "app.py"]
            if mode == "gradio"
            else [
                "yolo",
                "solutions",
                "inference",
                f"model={request['inputs'].get('model', 'yolo11n.pt')}",
            ]
        )
        return plan_response(
            request,
            "UI launch dry run prepared",
            "cli" if mode == "streamlit" else "subprocess",
            mode,
            params={"cmd": cmd_preview},
        )

    artifact_dir = ensure_manifest_dir(request)
    stdout_path = ensure_manifest_child(
        request, None, "launcher.stdout_path", f"{mode}.stdout.log"
    )
    stderr_path = ensure_manifest_child(
        request, None, "launcher.stderr_path", f"{mode}.stderr.log"
    )
    if mode == "gradio":
        cmd = [deps.python_executable, "app.py"]
        env = isolated_python_env(deps.python_executable, artifact_dir)
        url = request["params"].get("url", "http://127.0.0.1:7860")
    elif mode == "streamlit":
        model = request["inputs"].get("model") or "yolo11n.pt"
        yolo_path, _ = deps.ensure_yolo_cli()
        cmd = [yolo_path, "solutions", "inference", f"model={model}"]
        env = isolated_cli_env(yolo_path, artifact_dir)
        url = request["params"].get("url", "http://127.0.0.1:8501")
    else:
        raise ValueError(f"Unsupported ui launch mode: {mode}")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        stdout_path.open("ab") as stdout_handle,
        stderr_path.open("ab") as stderr_handle,
    ):
        process = subprocess.Popen(
            cmd,
            cwd=deps.repo_root,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            start_new_session=True,
        )
    payload = response(
        request["skill"],
        "running",
        f"{mode} launcher started",
        job={"mode": "async", "pid": process.pid, "url": url},
        logs={
            "stdout_path": str(stdout_path.resolve()),
            "stderr_path": str(stderr_path.resolve()),
        },
    )
    payload["manifest"] = str(write_manifest(request, payload))
    return payload
