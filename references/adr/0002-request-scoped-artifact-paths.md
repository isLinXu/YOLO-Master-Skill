# ADR 0002: Request-Scoped Artifact Paths

## Status

Accepted.

## Context

The Agent runtime accepts externally supplied task parameters and invokes YOLO CLI, Python APIs, and research
helpers. Several of those interfaces can write files based on path-like options, so one unchecked option could place
artifacts outside the request manifest or overwrite unrelated experiment data.

## Decision

- Route experiment directories exclusively through `artifacts.project` and `artifacts.name`, contained below
  `runs/agent/`.
- Reject `params.project`, `params.name`, and `params.save_dir` for regular YOLO executors.
- Resolve task-local output values only as relative children of the current request directory.
- Stage export model inputs in the request directory and run exports from that directory. Preserve `yolo.export`
  `params.name` only because several exporter backends use it as a hardware target identifier.
- Constrain release-audit manifests to `runs/agent/`, and constrain its supporting inputs to the YOLO-Master root.
- Cover acceptance and escape rejection with the `artifact_path_containment` contract probe.

## Consequences

Every request has a single provenance directory containing its manifest and generated artifacts. Callers needing a
different experiment root must choose it through the artifact envelope rather than pass output flags through a task.
Some direct underlying-library conveniences are intentionally unavailable through the Agent interface.
