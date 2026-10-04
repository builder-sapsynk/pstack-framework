---
name: monitor-agent-workflow
description: Record actual worker lifecycle, timing, usage sources, and harness breakpoints in private replayable events. Append deterministic two-line observed metrics to substantive workflow updates. Use for agent workflow monitoring or diagnosing coordination waits and failures.
---

# Monitor agent workflow

Read the installed [contract](../../adapters/CONTRACT.md), matching host adapter, [metrics contract](../../adapters/workflow-metrics.md), and project pin/config. Preserve provider, transport, source family, model, effort, host, and harness as separate facts. Monitoring does not authorize selection changes, provider calls, routing changes, or extra workers.

## Launch

Resolve `PSTACK_PACKAGE` from this skill's actual location, two directories above `SKILL.md`. Set `PSTACK_WORKFLOW` to a new private directory under the approved project `.pstack/runs` or workspace `.pstack-checks`. Python 3 and its standard library are sufficient. There is no persistent service.

Record `workflow-start` before the work and `workflow-end` after it. Use the same coordinator clock. Give each observed worker its own stable ID and event stream, and retain each native tool's real returned agent ID. Link children through `--parent-worker`. Use the durable runtime `job_id` as both worker ID and attempt ID when joining automatic runtime events with receipt imports. Preserve retry attempts and failures.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker coordinator --event workflow-start
```

## Doctor

Inspect the local command and write permissions before recording the workflow.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" --help
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --help
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --help
```

Confirm the package path matches the pin, evidence stays outside tracked source, and the host exposes actual native spawn/status/terminal observations. Native context and token counters may be unavailable. Doctor verifies command configuration only; it does not prove worker execution or provider availability.

## Drive

Use the existing approved workflow. Before a spawn, record `requested` with role, requested tuple, host, transport, parent, and fork control. After the tool returns, preserve its native ID and record the actual start observation. Record status observations, real progress, harness phase start/end, explicit failure codes, cancellation requests, and confirmed terminal outcomes. Never turn a cancellation request into confirmed cancellation.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker "$PSTACK_WORKER" --event requested --attempt "$PSTACK_ATTEMPT" --parent-worker coordinator --metadata @"$PSTACK_METADATA"
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker "$PSTACK_WORKER" --event started --attempt "$PSTACK_ATTEMPT"
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" import-receipt --workflow "$PSTACK_WORKFLOW" --receipt "$PSTACK_RECEIPT" --parent-worker coordinator
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW"
```

After each substantive commentary or final response, append the summary's two lines. Keep the order `Agents:` then `Tokens:`. Use a fixed `--cutoff` when saving an auditable snapshot. A formatter cannot decorate host messages automatically, so the coordinator must invoke it and append its output.

Inspect JSON when diagnosing breakpoints. Open stages, failed attempts, last progress age, and stale observation flags identify missing observations and recorded waits. They do not prove idle computation or utilization. Treat token counts as reported call volume. Keep current context occupancy unknown without a contemporary measurement and matching served model/configuration capacity. Do not infer cache definitions from provider names. Never change source-family selection automatically.

## Evidence

Keep original tool observations, event streams, runtime receipts, fixed-cutoff JSON snapshots, and the exact two-line output privately. Record which descendants are known. Only an explicit complete manifest plus all requested/started/terminal lifecycles can produce complete coverage. A terminal receipt alone cannot certify intermediate phases or all descendants.

The [feature map](features/README.md) provides lifecycle, resource-counter, and replay recipes. Exercise those paths against the actual local CLI. Unit events prove deterministic reduction and private evidence retention; they do not establish live provider access, general model quality, or native usage availability. A live monitoring proof must use the workflow's actual native agents and original provider receipts separately.

## Cleanup

There is no monitor process to stop. Cancel only jobs owned by the authorized workflow through their real host/runtime controls. Preserve event streams, terminal receipts, snapshots, and the proof index after scratch cleanup. Delete only named disposable files created by this drive. Keep credentials, raw prompts, provider profiles, unrelated chat transcripts, and private logs outside Git.

## Helpers

`runtime/workflow_metrics.py` provides `record`, `import-receipt`, and `summary`. `summary --json` exposes phases, per-worker age, attempt failures, raw numerical receipt counters, counter definitions, and evidence location. Repeated receipt imports are idempotent. Invalid metadata or conflicting event identities exit 2. Read-only replay preserves the files.

In a source checkout, run the behavioral checks without provider calls.

```bash
python3 -m unittest discover -s "$PSTACK_PACKAGE/tests" -p test_workflow_metrics.py -v
```

Tests are source verification assets; installed release packages may omit them. Use the feature recipes for packaged CLI verification. Extend this skill and map when a host exposes trustworthy contemporary context measurements or new lifecycle events. Keep absent instrumentation explicit.
