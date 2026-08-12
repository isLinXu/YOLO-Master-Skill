"""Resolve the YOLO-Master checkout used by this standalone Skill bundle."""

from __future__ import annotations

import os
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
_ENV_ROOT = "YOLO_MASTER_ROOT"


def _is_yolo_master_root(path: Path) -> bool:
    """Return whether a path looks like a YOLO-Master source checkout."""
    return (path / "ultralytics" / "__init__.py").is_file() and (
        path / "pyproject.toml"
    ).is_file()


def _candidate_roots() -> list[Path]:
    """Return supported implicit checkout locations in priority order."""
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents, SKILL_ROOT.parent]
    sibling = SKILL_ROOT.parent / "YOLO-Master"
    if sibling not in candidates:
        candidates.append(sibling)
    return candidates


def resolve_yolo_master_root() -> Path:
    """Locate the YOLO-Master checkout, honoring ``YOLO_MASTER_ROOT`` first."""
    configured = os.environ.get(_ENV_ROOT)
    if configured:
        root = Path(configured).expanduser().resolve()
        if _is_yolo_master_root(root):
            return root
        raise RuntimeError(
            f"{_ENV_ROOT} must point to a YOLO-Master checkout containing ultralytics/__init__.py: {root}"
        )

    for root in _candidate_roots():
        if _is_yolo_master_root(root):
            return root

    raise RuntimeError(
        "Could not locate a YOLO-Master checkout. Set YOLO_MASTER_ROOT to the repository root before running this Skill."
    )


YOLO_MASTER_ROOT = resolve_yolo_master_root()


def skill_path(*parts: str) -> Path:
    """Return a path owned by this standalone Skill bundle."""
    return SKILL_ROOT.joinpath(*parts)
