"""Agent handler for read-only release bundle audits."""

from __future__ import annotations

from typing import Any

from ..release import audit_manifest, write_release_bundle

from .contract import ensure_manifest_child, ensure_path_within, plan_response, response
from .normalize import is_dry_run
from runtime.paths import YOLO_MASTER_ROOT


REPO_ROOT = YOLO_MASTER_ROOT
DEFAULT_GOVERNANCE_REGISTRY = REPO_ROOT / "docs" / "governance" / "model-registry.yaml"
DEFAULT_EXPORT_MATRIX = (
    REPO_ROOT / "ultralytics" / "cfg" / "export-capability-matrix.yaml"
)


def run_release_audit(request: dict[str, Any]) -> dict[str, Any]:
    """Audit a versioned Agent manifest and optionally write its bundle."""
    inputs = request.get("inputs", {})
    params = request.get("params", {})
    manifest = inputs.get("manifest") or params.get("manifest")
    if not manifest:
        raise ValueError("`inputs.manifest` or `params.manifest` is required.")
    manifest_path = ensure_path_within(
        manifest, "inputs.manifest", REPO_ROOT / "runs" / "agent"
    )
    artifact_root = params.get("artifact_root")
    governance = params.get("governance_registry", str(DEFAULT_GOVERNANCE_REGISTRY))
    export_matrix = params.get("export_matrix", str(DEFAULT_EXPORT_MATRIX))
    audit_params = {
        "governance_registry": str(
            ensure_path_within(governance, "params.governance_registry", REPO_ROOT)
        ),
        "export_matrix": str(
            ensure_path_within(export_matrix, "params.export_matrix", REPO_ROOT)
        ),
    }
    artifact_root_path = (
        ensure_path_within(artifact_root, "params.artifact_root", REPO_ROOT)
        if artifact_root
        else None
    )
    output_path = ensure_manifest_child(
        request,
        params.get("output"),
        "params.output",
        "release_bundle.json",
    )
    if is_dry_run(request):
        return plan_response(
            request,
            "release audit dry run prepared",
            "module",
            "audit_manifest",
            params={
                "manifest": str(manifest_path),
                "artifact_root": str(artifact_root_path)
                if artifact_root_path
                else None,
                **audit_params,
            },
            next_actions=["run with policy.dry_run=false to write release_bundle.json"],
        )

    bundle = audit_manifest(
        manifest_path,
        params=audit_params,
        artifact_root=artifact_root_path,
    )
    output_path = write_release_bundle(bundle, output_path)
    return response(
        request["skill"],
        "ok" if bundle.decision.status != "refused" else "partial",
        f"release audit completed: {bundle.decision.status}",
        release=bundle.to_dict(),
        decision=bundle.decision.to_dict(),
        artifacts=[{"kind": "release_bundle", "path": str(output_path)}],
        next_actions=[]
        if bundle.decision.status == "publishable"
        else ["resolve release decision reasons before publishing"],
    )


__all__ = ["run_release_audit"]
