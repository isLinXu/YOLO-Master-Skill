---
name: yolo-master-agent
description: Operate a separately checked-out YOLO-Master instance through structured train, validation, inference, export, MoE, PEFT, multimodal, release-audit, and async-job workflows.
---

# YOLO-Master Agent Skill

## Setup

This is a standalone Skill bundle. It requires a separate YOLO-Master checkout and uses its local Ultralytics package
and `yolo` CLI. Set `YOLO_MASTER_ROOT` before invoking a script unless the bundle is nested in that checkout.

```bash
export YOLO_MASTER_ROOT=/path/to/YOLO-Master
python -m pip install -e "$YOLO_MASTER_ROOT"
python scripts/run_yolo_master_skill.py --json \
  '{"skill":"yolo.system","action":"doctor","params":{"ensure_cli":false},"policy":{"dry_run":true}}' --pretty
```

## Supported Skills

- Core: `yolo.train`, `yolo.lora.train`, `yolo.val`, `yolo.predict`, `yolo.track`, `yolo.export`, `yolo.benchmark`, `yolo.tune`.
- Inspection and system: `yolo.system`, `yolo.model.inspect`, `yolo.lora.adapters`, `yolo.lora.diagnose`.
- MoE and evaluation: `yolo.moe.diagnose`, `yolo.moe.prune`, `yolo.eval.peft_compare`, `yolo.eval.sparse_sahi_compare`.
- Multimodal: `yolo.multimodal.infer`, `yolo.multimodal.evaluate`.
- Orchestration: `yolo.pipeline.experiment`, `yolo.release.audit`, `yolo.job.status`, `yolo.job.cancel`.
- Launchers: `yolo.solutions.run`, `yolo.ui.launch`.

## Request Contract

```json
{
  "skill": "yolo.train",
  "runtime": {"prefer_cli": true, "prefer_mps": true},
  "inputs": {"model": "yolo11n.pt", "data": "coco8.yaml"},
  "params": {"epochs": 1, "imgsz": 640},
  "policy": {"dry_run": true}
}
```

Use `policy.dry_run=true` before any costly operation. `params` carries task-specific YOLO arguments. On Apple Silicon,
the dispatcher selects MPS for compute-heavy jobs when possible and retries once on CPU only when it selected the
device automatically and encounters a device-runtime failure.

The dispatcher emits a structured response and a redacted, versioned `skill_manifest.json`. Experiment artifacts and
manifests are written in the YOLO-Master checkout under `runs/agent/` by default.

## Examples

Train plan:

```bash
python scripts/run_yolo_master_skill.py --json \
  '{"skill":"yolo.train","inputs":{"model":"yolo11n.pt","data":"coco8.yaml"},"params":{"epochs":1,"imgsz":32},"policy":{"dry_run":true}}' --pretty
```

Multimodal plan:

```bash
python scripts/run_yolo_master_skill.py --json \
  '{"skill":"yolo.multimodal.infer","inputs":{"model":"yolo11n.pt","source":"ultralytics/assets/bus.jpg","prompt":"Identify the important objects."},"params":{"thinking_with_image":true,"structured_output":true,"prompt_template":"vlm_open_world_detection"},"policy":{"dry_run":true}}' --pretty
```

Release audit:

```bash
python scripts/run_yolo_master_skill.py --json \
  '{"skill":"yolo.release.audit","inputs":{"manifest":"runs/agent/experiment/skill_manifest.json"},"policy":{"dry_run":true}}' --pretty
```

## Multimodal Rules

`yolo.multimodal.infer` runs detector evidence first and optionally calls an OpenAI-compatible VLM/LLM service.
Set `OPENAI_API_KEY`, or `DASHSCOPE_API_KEY` with `params.provider="dashscope"`, only for real multimodal runs.

- Prompt templates live in `assets/prompts/`.
- `structured_output=true` enables parsed verdicts.
- `use_marked_image=true` enables numbered detection evidence.
- `visual_search_mode=auto` permits crop-and-zoom follow-up requests.
- `fusion_mode=preview` creates metric-safe fusion proposals; the default `fusion_policy=add_only` allows only guarded additions.
- `fusion_policy=open_world_assist` preserves novel unmapped predictions for reasoning, using the bundled LVIS/V3Det taxonomy.

Do not expose API keys in requests or artifacts. The manifest redacts secret-looking fields and inline credentials.

## Validation

```bash
python scripts/validate_yolo_master_skill.py --suite quick --pretty --summary-only
```

`quick` combines fast smoke, dry-run, and contract coverage. Use `all` only when intentionally running the full
non-manual suite. `extended` contains real CLI probes and is manual-only.

## Release Audit

The release audit only consumes evidence explicitly referenced by a manifest, hashes every eligible file, and returns
`publishable`, `experimental`, or `refused`. It never copies checkpoints, builds a model, or scans arbitrary run
directories.

```bash
python scripts/audit_release_manifest.py runs/agent/experiment/skill_manifest.json \
  --output runs/agent/experiment/release_bundle.json --fail-on experimental
```
