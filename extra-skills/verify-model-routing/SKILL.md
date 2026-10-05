---
name: verify-model-routing
description: Verify setup-pstack model, effort, provider, host and harness choices through actual terminal receipts and independently checked artifacts. Use for a quick availability smoke or a repeated local quality, latency and cost comparison before changing role bindings.
---

# Verify model routing

This is a portable verification skill for pstack setup. It measures options on the user's declared tasks. It does not prescribe a project-specific model table or rank general model capability. Read the installed [contract](../../adapters/CONTRACT.md), the matching host adapter, [selection policy](../../adapters/model-selection.md), and the project's pin/config before driving anything. Retain role labels, panel counts and approved budget. Never update the project pin or role bindings as a side effect of a probe.

## Launch

There is no persistent service. Resolve the package root from this loaded skill's location, two directories above `SKILL.md`. Set `PSTACK_PACKAGE` to that absolute root and `PSTACK_PROJECT` to the approved absolute checkout. Use the existing Python 3 standard-library CLI. No package installation is required.

Discover the current host's native model/effort schema and provider tools first. A model listed by a provider may require an external transport. A different host or harness creates a different option, even for the same model. Record provider, transport, model, effort, host and harness separately. Resolve inherited bindings before measuring; do not manufacture a native slug for an external provider. An unavailable combination remains unavailable.

Create one private evidence directory under the approved project `.pstack/runs` or workspace `.pstack-checks`. Store the immutable task definition, bounded request, terminal receipt, response/artifact, checker output and summary there. Each attempt has its own directory and actual terminal receipt. Credentials and private logs stay out of Git.

## Doctor

Run the read-only installation/authentication preflight.

```bash
python3 "$PSTACK_PACKAGE/runtime/cli.py" doctor --project "$PSTACK_PROJECT" --json
```

On an owner-controlled Claude Code host the worker lane is the project's `scripts/pstack-run`, so run `scripts/pstack-run doctor` as well; there the request-file doctor reports Grok blocked by Claude Code's plugins, as [the doctor feature](features/doctor.md) explains. Inspect every provider's JSON status and version. Doctor can return a nonzero exit while reporting the individual provider checks. A ready preflight establishes installation/authentication readiness, not completed work. If discovery or auth is unavailable, report it before attempting a drive. Reuse the current project's verifier when one exists.

## Drive

Start with a safe, unrelated synthetic task when project-data transfer is not authorized. A real provider response to a synthetic task is captured evidence; a fake provider executable is a unit fixture. Keep that distinction in the summary.

For the response-only Grok Build dialect, create a request with `dialect` exactly `{"id":"grok-build-1","confinement":"response-only"}`, the discovered model and effort, `mode` `read-only`, the approved absolute `cwd`, and a private absolute `prompt_file`. The runtime owns exact supported flags and structured event parsing. Read [Grok transport](../../runtime/README.md) rather than inventing CLI flags. Response-only execution disables provider file/command tools. State in the bounded brief that this worker has no workspace tools and must return the requested artifact directly, without promising later actions. The coordinator stores the returned artifact and runs the approved local checker. If it fails, retain that attempt and issue a separately recorded repair request; never replace a failed comparison run with the retry. This proves response/artifact generation; it does not prove the provider edited or tested files. For native file/command lanes, first drive the packaged [verify-agent-parity](../verify-agent-parity/SKILL.md) with the qualified managed-host adapter. A response-only proof cannot promote those lanes. If no qualified host boundary exists, mark writer/file-read lanes blocked. Never relax confinement to make a failing lane count as successful.

The request shape is `{"provider":"grok","model":<discovered model>,"effort":<discovered effort>,"mode":"read-only","project":<approved absolute project>,"cwd":<approved absolute cwd>,"prompt_file":<private absolute prompt path>,"dialect":{"id":"grok-build-1","confinement":"response-only"}}`. Replace the bracketed values with the discovered binding and saved paths before writing valid JSON. Configure `GROK_BINARY` and `GROK_HOME` externally for the authenticated installed CLI, or use the runtime's supported executable setting. Never include credentials in the request. Environment paths depend on this host; do not copy another host's profile path.

Set `PSTACK_REQUEST` to that saved request's absolute path. Retain the terminal session and emitted durable job ID.

```bash
python3 "$PSTACK_PACKAGE/runtime/cli.py" run --project "$PSTACK_PROJECT" --request "$PSTACK_REQUEST"
```

For other providers or native host workers, use the matching adapter's actual supported controls and normalize the captured receipt as documented in [the record contract](../../adapters/model-selection.md). Keep the original native receipt. Preserve selected binding, served-model evidence, terminal status, measured elapsed time, source identity and usage metadata. Do not count a provider's claim that its own answer passes as artifact verification.

A smoke needs at least one attempt per option. Independently inspect the actual artifact with the task's acceptance checks. Record zero quality points for unverified work or terminal failures. Summarize the saved record bundle.

```bash
python3 "$PSTACK_PACKAGE/runtime/model_selection.py" --input "$PSTACK_RECORDS" --mode smoke --output "$PSTACK_SUMMARY"
```

Set `PSTACK_RECORDS` and `PSTACK_SUMMARY` to the private absolute input/output paths. Smoke reports availability only. One fast response is never a speed winner.

For selection, freeze representative task definitions and acceptance checks before launching candidates. Perform at least five complete interleaved rounds for each task, with every option once per round. Rotate the first option when practical. Preserve actual dispatch/terminal chronology in the harness transcript and put attempts in that observed order in the bundle. The summarizer validates recorded round order; a reordered list alone is not proof of chronological interleaving. Count failures, cancellations, timeouts and malformed outputs. Run the benchmark checklist against real evidence, including the limiter and settings. Account subscription tiers or a CLI's `total_cost_usd` estimate do not establish measured billed cost.

```bash
python3 "$PSTACK_PACKAGE/runtime/model_selection.py" --input "$PSTACK_RECORDS" --mode selection --output "$PSTACK_SUMMARY"
```

Default weights are declared policy, quality 0.70, latency 0.15 and cost 0.15. The quality gate requires mean quality at least 85 for every task and zero critical violations. Failures receive zero points and remain in the denominator. Known measured cost is required when cost has positive weight. An explicitly declared zero cost weight allows a comparison that makes no cost claim. Variation overlap, missing repeats/checklist evidence or unknown required cost makes selection inconclusive. Preserve the incumbent on inconclusive evidence. Apply a selected option to roles only within the user's authorized setup scope; preserve judgment roles and panel requirements.

## Evidence

Use the rubric and strict JSON contract in [model-selection.md](../../adapters/model-selection.md). The independent check binds its scores to the artifact and terminal receipt hashes. Preserve exact scores, task specification digest, tests/output, failed attempts, median/range, declared weights, uncertainty and unmet boundaries. Hashes detect mutation; they do not certify an honest capture or prove that arbitrary checks are adequate. The coordinator remains responsible for inspecting original events and the resulting work.

The [feature map](features/README.md) covers doctor, availability smoke and repeated selection. Exercise a real mapped path before declaring this skill verified. A parser test with fabricated evidence cannot establish live provider access. Keep a real-run receipt/check/summary privately; publish only sanitized metadata when authorized. Do not claim general capability rankings from a small toy task.

## Cleanup

The short-lived runtime exits after each drive. Cancel only an actual job this drive started using its retained job ID and runtime cancellation command when needed. Delete only proven disposable scratch created by this verification. Preserve terminal receipts, native events, generated artifacts, checker output and summaries. Confirm they remain readable after cleanup. Never kill by process name, remove shared provider profiles, scan unrelated transcripts or delete another chat's files.

## Helpers

`runtime/model_selection.py` is executable and uses Python's standard library. It reads local evidence only and never launches providers. `--mode smoke` establishes observed availability; `--mode selection` evaluates repeated evidence; malformed evidence exits 2. A valid inconclusive report exits 0 and has `verdict` `inconclusive`. Inspect the verdict before making a choice. `--allow-unit-fixtures` permits parser demonstrations but never establishes availability or selects a model.

The bundled [unit fixture](fixtures/unit-smoke.json) is explicitly fabricated. From this skill's directory, exercise the helper without external calls.

```bash
python3 ../../runtime/model_selection.py --input fixtures/unit-smoke.json --mode smoke --allow-unit-fixtures
```

Use the packaged [maintain-verification-skill](../maintain-verification-skill/SKILL.md) as features, controls and receipt schemas change. Extend this map when new native hosts or provider harnesses are actually verified.
