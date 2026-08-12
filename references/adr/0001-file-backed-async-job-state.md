# ADR 0001: File-Backed Async Job State

## Status

Accepted

## Context

The standalone Skill runs long YOLO-Master operations locally. The original async implementation stored a child PID and
reported `completed` whenever that PID was absent. A missing PID cannot prove success, cannot distinguish a process
failure from cancellation, and can be reused by an unrelated process. It also persisted raw request bodies and allowed
caller-controlled manifest paths outside the intended experiment root.

## Decision

Use one local runner process per job, backed by an isolated directory under the Skill-local ignored
`logs/async-jobs/<12-hex-id>/` path. The runner starts the dispatcher child, parses its structured response, writes a
redacted `result.json`, and atomically records one terminal state:

- `succeeded`: child exits zero and returns `ok` or `partial`.
- `failed`: dispatcher response is unsuccessful or the child/runner fails.
- `cancelled`: the runner receives and completes a cancellation request.
- `interrupted`: a non-terminal runner disappears before it records a terminal state.

Job IDs are fixed lowercase hexadecimal identifiers. Lookups never create directories. Status checks use runner
liveness only for non-terminal jobs and never infer success from PID absence. Cancellation is two-phase: status is
first `cancelling`, then only the runner writes `cancelled`.

Persisted request, status, and result payloads are redacted. Inline request credentials are not a supported transport;
real provider credentials must come from the runner environment. Callback URLs are recorded only as a boolean because
the runtime does not implement callback delivery.

Manifests are constrained to the YOLO-Master checkout's `runs/agent/` root. Project values must be relative: simple
labels map to `runs/agent/<label>` and explicit paths must remain contained by that root. Absolute paths and traversal
paths are rejected.

## Consequences

The runtime gains durable, inspectable terminal outcomes without introducing an external queue service or database.
The runner adds one short-lived process and file I/O per job, which is acceptable for a local Skill and keeps deployment
requirements minimal. Jobs are local to the host and are not restartable after a machine reboot; an abandoned job is
reported as `interrupted`, not falsely successful. Production multi-host scheduling, authorization, retention policies,
and callback delivery remain deliberately out of scope.

## Verification

The contract probe starts a dry-run job and an intentional failure, asserts their terminal states, verifies request and
result redaction, rejects malformed job IDs, and rejects manifest path escape attempts.
