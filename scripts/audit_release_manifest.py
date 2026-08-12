#!/usr/bin/env python3
"""Audit a YOLO-Master Agent manifest and write its release bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.paths import YOLO_MASTER_ROOT  # noqa: E402
from runtime.release import audit_manifest, write_release_bundle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse release preflight options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to a skill_manifest.json")
    parser.add_argument(
        "--artifact-root", type=Path, help="Permitted root for referenced evidence"
    )
    parser.add_argument(
        "--governance-registry",
        type=Path,
        default=YOLO_MASTER_ROOT / "docs" / "governance" / "model-registry.yaml",
    )
    parser.add_argument(
        "--export-matrix",
        type=Path,
        default=YOLO_MASTER_ROOT
        / "ultralytics"
        / "cfg"
        / "export-capability-matrix.yaml",
    )
    parser.add_argument("--output", type=Path, help="Release bundle output path")
    parser.add_argument(
        "--fail-on",
        choices=("refused", "experimental"),
        default="refused",
        help="Decision threshold that returns a non-zero exit code",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the audit, emit JSON, and apply the requested decision threshold."""
    args = parse_args(argv)
    bundle = audit_manifest(
        args.manifest,
        params={
            "governance_registry": str(args.governance_registry),
            "export_matrix": str(args.export_matrix),
        },
        artifact_root=args.artifact_root,
    )
    output = args.output or args.manifest.parent / "release_bundle.json"
    output_path = write_release_bundle(bundle, output)
    payload = bundle.to_dict()
    payload["output"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on == "experimental" and bundle.decision.status in {
        "experimental",
        "refused",
    }:
        return 1
    if args.fail_on == "refused" and bundle.decision.status == "refused":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
