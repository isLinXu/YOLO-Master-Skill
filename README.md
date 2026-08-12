# YOLO-Master Skill

Standalone agentic runtime for [YOLO-Master](https://github.com/Tencent/YOLO-Master). It packages the Agent Skill
contract, CLI dispatcher, multimodal/open-world helpers, release-audit tooling, and AutoTrain-style validation cases
without duplicating the YOLO-Master framework, model definitions, or training outputs.

## Contents

- `SKILL.md`: agent-facing operating contract and supported `yolo.*` capabilities.
- `runtime/`: dispatcher, async jobs, structured manifests, multimodal VLM/LLM workflows, MoE/PEFT helpers, and release audits.
- `scripts/`: executable entry points for dispatch, validation, open-world reports, and release audits.
- `assets/`: prompt templates, taxonomy data, a tiny detection dataset, and validation cases.
- `metadata/`: Skill presentation metadata.
- `references/`: architecture and thinking-with-image documentation.

## Prerequisites

Clone YOLO-Master separately, then point this Skill at that checkout. `YOLO_MASTER_ROOT` is required when the Skill is
not located inside a YOLO-Master tree. The dispatcher also discovers a checkout from the current directory or its
parents when possible.

```bash
git clone git@github.com:Tencent/YOLO-Master.git /path/to/YOLO-Master
export YOLO_MASTER_ROOT=/path/to/YOLO-Master
python -m pip install -e "$YOLO_MASTER_ROOT"
```

The dispatcher uses the framework's editable install and its `yolo` CLI. It writes normal experiment artifacts to the
YOLO-Master checkout under `runs/agent/`; local Skill logs are ignored under `logs/`.

## Run

Use the structured dispatcher from this repository:

```bash
export YOLO_MASTER_ROOT=/path/to/YOLO-Master
python scripts/run_yolo_master_skill.py --json \
  '{"skill":"yolo.system","action":"doctor","params":{"ensure_cli":false},"policy":{"dry_run":true}}' --pretty
```

The request envelope accepts a `skill`, `inputs`, `params`, `runtime`, `artifacts`, and `policy` object. See
[`SKILL.md`](SKILL.md) for the supported operations and examples.

For longer tasks, set `policy.async=true` to submit a subprocess job. Poll it with `yolo.job.status`; terminal states
are `succeeded`, `failed`, `cancelled`, and `interrupted`, and the status records the redacted `result.json` path.
`yolo.job.cancel` records a cancellation request first, then the runner confirms `cancelled` after its child exits.
The optional `callback_url` is retained only as a redacted configuration signal; this local runtime does not dispatch
HTTP callbacks. Async request snapshots and result files live under this Skill's ignored `logs/async-jobs/` directory.

## Validation

The default quick suite runs fast smoke, dry-run, and contract cases. It does not start model training or issue VLM
requests.

```bash
export YOLO_MASTER_ROOT=/path/to/YOLO-Master
python scripts/validate_yolo_master_skill.py --suite quick --pretty --summary-only
```

Use `--suite all` only for the complete non-manual test pack. `extended` includes manually enabled real CLI probes.

## License

This repository contains code and assets extracted from YOLO-Master / Ultralytics and is distributed under
[AGPL-3.0](LICENSE). The original project and framework remain separate repositories.
