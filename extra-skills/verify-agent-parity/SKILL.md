---
name: verify-agent-parity
description: Drive actual external pstack workers to verify native-like file tools, commands, durable jobs and resumable sessions. Use before promoting a provider or claiming parity with the coordinating host.
---

# Verify agent parity

Read the [contract](../../adapters/CONTRACT.md), matching host adapter and [direct Grok adapter](../../adapters/grok-native.md). Resolve this installed package from the skill path. Preserve project pins and role panels. Qualification is specific to provider, model, effort, host, transport and actual tools. A native collaboration API and an external CLI are different transports.

## Launch

There is no server to keep alive. Use Python 3 and an already authenticated official provider CLI. Set `PSTACK_PACKAGE` to the installed package root, `PSTACK_PROJECT` to the authorized checkout, and `PSTACK_EVIDENCE` to a new private directory under `.pstack/runs` or workspace `.pstack-checks`. Never put credentials in requests or Git. Use the current host's managed execution tool with its permitted network route.

For an unrelated synthetic fixture, initialize a private Git project with `calc.py` containing `def add(a, b): return a - b`, a `check.py` with literal positive/negative/zero addition assertions, and `.gitignore` excluding `.pstack/` and `__pycache__/`. Set the repository identity from approved project policy, commit the fixture, then add a distinct writer worktree. Freeze these checks before inference. Existing project work uses its own verifier in an owned worktree.

## Doctor

```bash
python3 "$PSTACK_PACKAGE/runtime/cli.py" doctor --project "$PSTACK_PROJECT" --json
```

Inspect each provider's status. Doctor alone never proves live tools. Read the host permission declaration and retain it with the evidence. For managed native tools, the runtime's denied-write canary must pass before inference. Missing or incompatible host enforcement blocks that lane; use a response-only lane or a separately verified broker.

## Drive

Write a private JSON request with provider `grok`, discovered model `grok-4.7`, approved effort `medium`, mode `isolated-write`, absolute project/worktree paths, dialect `{"id":"grok-build-native-1","confinement":"managed-host"}`, the actual supported host boundary declaration from the direct adapter, exact `allowed_commands` containing `python3 check.py`, an explicit task brief to read/fix/check the fixture, and a private absolute `workflow` directory. The host boundary example applies only to this qualified Codex cloud; discover it again elsewhere.

```bash
python3 "$PSTACK_PACKAGE/runtime/cli.py" run --request "$PSTACK_REQUEST"
```

Retain the emitted job ID and host terminal handle. Drain the actual terminal result. Inspect native init inventory, served model, successful tool calls/results, actual disk mutation and command exit/output. Independently rerun the frozen check through the host. Confirm main fixture files stayed unchanged while the worker's files changed.

Use the emitted absolute job path for `status`, `checkpoint` and `cancel`. A follow-up request with `resume_job` set to a completed job preserves its provider/model/cwd/mode and native session. Ask for prior context and rerun the check. Confirm the same native session, new durable job and real tool execution. Resume is not live native messaging. Exercise live cancellation only on a job you launched and verify the owned provider/command processes are gone. Remote API termination remains unknown unless the provider exposes evidence.

## Evidence

Capture immutable task/check source, host tool transcript, requests, receipts, native streams, original/changed artifacts and independent verifier output. Bind them by SHA-256. Write a bundle with `schemaVersion: 1`, `evidenceKind: captured` and `runs`. Each run has candidate, task, binding and evidence. Binding contains provider/transport/model/effort/host/harness. Evidence references are objects with exact path/sha256 for task, receipt, native, artifact and verification, plus supporting lifecycle proof files as needed.

The independent verification JSON uses kind `artifact-check`, source `independent-observation`, verifier distinct from candidate, task/taskDigest, exact evidenceSha256 for every other evidence file, boolean workVerified/criticalViolation and capability observations. Each capability has status (`verified`, `partial`, `blocked`, `unknown`), detail and observation names. Read the helper's schema errors rather than relaxing a failed gate. Native tool calls and independent actual work are required for read/edit/verify. Fixtures do not establish availability. Hashes detect mutation, not dishonest capture.

```bash
python3 "$PSTACK_PACKAGE/runtime/agent_parity.py" --input "$PSTACK_BUNDLE" --output "$PSTACK_SUMMARY"
```

The [feature map](features/README.md) covers tools, confinement, lifecycle and persistent follow-up. Prove one real mapped feature before handing over the skill. Report the capability matrix, including gaps. Never turn a toy check into universal superiority or full native API/isolation parity. Context occupancy is distinct from reported aggregate token volume.

## Cleanup

Drain or cancel only owned jobs. Remove only disposable instances created by this drive after preserving artifact/check evidence; do not delete provider homes needed for the resume proof. Preserve receipts, private sessions and evidence through cleanup. Confirm they remain readable. Never kill by process name or remove shared authentication.

## Helpers

`runtime/cli.py` owns execution, job status, checkpoints and cancellation. `runtime/agent_parity.py` reads evidence locally and never starts a model. `runtime/workflow_metrics.py summary --workflow "$PSTACK_WORKFLOW"` returns deterministic two-line metrics. Run the packaged maintain-verification-skill workflow when controls or capability contracts change.
