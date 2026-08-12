from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime.cli.async_jobs import AsyncJobManager
from runtime.cli.contract import response


STATUS_RESPONSE_STATUS = {
    "queued": "ok",
    "running": "ok",
    "cancelling": "ok",
    "succeeded": "ok",
    "cancelled": "ok",
    "failed": "failed",
    "interrupted": "failed",
    "missing": "failed",
}


@dataclass(frozen=True)
class JobDeps:
    manager_factory: Callable[[], AsyncJobManager] = AsyncJobManager


def requested_job_id(request: dict[str, Any]) -> str:
    job_id = request["inputs"].get("job_id") or request["params"].get("job_id")
    if not job_id:
        raise ValueError("`inputs.job_id` or `params.job_id` is required.")
    return str(job_id)


def run_job_status(
    request: dict[str, Any], deps: JobDeps = JobDeps()
) -> dict[str, Any]:
    status = deps.manager_factory().status(requested_job_id(request))
    state = str(status.get("status", "missing"))
    return response(
        request["skill"],
        STATUS_RESPONSE_STATUS.get(state, "failed"),
        "async job status collected" if state != "missing" else "async job not found",
        job=status,
    )


def run_job_cancel(
    request: dict[str, Any], deps: JobDeps = JobDeps()
) -> dict[str, Any]:
    status = deps.manager_factory().cancel(requested_job_id(request))
    state = str(status.get("status", "missing"))
    requested = bool(status.get("cancel_requested"))
    cancelled = state == "cancelled"
    return response(
        request["skill"],
        "ok" if requested or cancelled else "partial",
        "async job cancelled"
        if cancelled
        else "async job cancellation requested"
        if requested
        else "async job was not running",
        job=status,
    )
