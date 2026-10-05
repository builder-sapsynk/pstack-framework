# Workflow metrics contract

`runtime/workflow_metrics.py` records local lifecycle observations and reduces them into a timestamp-scoped snapshot. It neither starts workers nor changes routing. The coordinator invokes the formatter after substantive commentary and final output. A Python formatter cannot automatically decorate host messages.

## Private events

Each workflow uses an explicit private directory under project `.pstack/runs` or workspace `.pstack-checks`. Each worker has one owned JSONL file in `events`. The coordinator owns its native-worker observation stream. Worker filenames use a hash of the worker ID. The workflow and events directories have mode `0700`; event files have mode `0600`. A same-worker lock protects append integrity. Reading merges independent files; there is no shared writable summary.

Every event contains `schemaVersion`, `workflowId`, `workerId`, `parentWorkerId`, `attemptId`, `eventId`, `seq`, `kind`, `observedAt`, `source`, `evidenceRef`, and `metadata`. `workflowId` is the directory's basename. `observedAt` requires an ISO timestamp with timezone. An optional `monotonicSeconds` requires `clockId`. Automatic local recording uses the machine boot ID and monotonic clock. Imported historical timings require their original clock identity; observation time alone cannot establish elapsed time.

Supported events are `registered`, `requested`, `started`, `observed-running`, `progress`, `phase-start`, `phase-end`, `complete`, `failed`, `cancellation-requested`, `cancelled`, `usage`, `context`, `workflow-start`, and `workflow-end`. Cancellation requests preserve the current lifecycle state. Unique worker counts exclude workflow events and events with `metadata.root` set to `true`. Attempts remain separate; JSON reports `failedAttempts` even when a later attempt succeeds.

Metadata accepts role, host, provider, transport, requested and resolved binding tuples, binding evidence, native agent ID, durable job ID, stage, phase ID, measured durations, usage, context, fork setting, brief bytes, failure code, and root manifest. It rejects unsupported fields such as raw prompts, credential dictionaries, and environment dumps. Keep evidence references local and scoped. A role or requested tuple does not prove the served tuple. Preserve unknown served models and efforts.

## CLI

Set `PSTACK_PACKAGE` to the actual package root and `PSTACK_WORKFLOW` to the workflow's private absolute directory. Record a native spawn request using the host's real returned worker ID.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker "$PSTACK_WORKER" --event requested --metadata '{"role":"implementation","host":"codex","transport":"native","fork_turns":"none"}'
```

Record `started`, `observed-running`, `progress`, and the actual terminal outcome through the same command. Supply `--parent-worker` for descendants and `--attempt` for retries. `--metadata @/absolute/metadata.json` reads a saved JSON object. Supply `--source`, `--evidence-ref`, and `--event-id` when those facts are available. An event ID replay is idempotent; conflicting evidence with the same ID fails.

Record explicit workflow start and end events with the same coordinator clock. They provide workflow wall time; elapsed worker times remain independent. `--clock-id` and `--monotonic-seconds` preserve an observed external clock. Different clock IDs yield unknown cross-clock durations. `phase-start` and `phase-end` pair through `phaseId` or `stage` within an attempt. JSON reports each phase duration and open stages without adding overlapping phases into exclusive work time.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker coordinator --event workflow-start
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" import-receipt --workflow "$PSTACK_WORKFLOW" --receipt "$PSTACK_RECEIPT" --parent-worker coordinator
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker coordinator --event workflow-end
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW"
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW" --json
```

`summary --import-receipt /absolute/receipt.json` imports before reducing and is repeatable. Receipt imports require a durable `job_id`. Runner status.json receipts are accepted. Safe metadata is copied; prompts, response text, credentials, environment variables, and `modelUsage` duplicates are excluded. The worker defaults to the job ID. To join runtime events and imports, use that same worker ID and attempt ID in both streams.

`--cutoff` scopes replay to a fixed timestamp. `--manifest /absolute/manifest.json` reads `{"complete":true,"workers":["worker-a","worker-b"]}`. A manifest must declare the whole descendant set. Complete coverage requires exact worker membership and observed request, start, and terminal events for each attempt. A terminal receipt alone remains partial. Unknown manifests, omitted descendants, nonterminal workers, and missing lifecycle observations remain partial.

`--stale-after` defaults to 300 seconds. JSON reports time since the last observation and independently time since the last progress event. `observed-running` refreshes the observation age, not the progress age. A stale observation does not prove stalled work or idle capacity.

## Python integration

The public functions are:

```python
record_event(workflow, worker, kind, metadata=None, *, parent_worker=None,
             attempt='1', source='coordinator', evidence_ref=None,
             observed_at=None, clock_id=None, monotonic_seconds=None, event_id=None)
import_receipt(workflow, receipt, *, worker=None, parent_worker=None)
summarize(workflow, *, cutoff=None, manifest=None, stale_after=300)
format_summary(summary)
```

`receipt` accepts a dictionary or path. The first two functions return the persisted event. `summarize` returns JSON-compatible data. `format_summary` returns exactly two lines in fixed order, beginning with `Agents:` and `Tokens:`. Append those lines to the host output using the current snapshot. No function executes a provider or modifies selection policy.

## Token and context meaning

Usage metadata contains optional `input`, `output`, `cacheRead`, `cacheWrite`, `inputDefinition`, `source`, `quality`, `sampleId`, `scope`, `sessionId`, numerical `raw` counters, and `volumeScope`. `scope` is `attempt` or `session`; session counters require `sessionId`. `volumeScope` can describe last-call or all-calls evidence. Keep that distinction in original metadata. Latest cumulative counters replace older counters in the same scope. Identical sample IDs replace duplicate representations. Distinct overlapping attempt and session aggregates have unknown normalized totals.

Only reported or measured counters with a source are eligible for normalization. `inputDefinition` is `includes_cache`, `excludes_cache`, or `unknown`. `includes_cache` preserves input without adding cache again. `excludes_cache` adds input, cache reads, and cache writes only when all three are known. Unknown definitions produce unknown normalized input totals. Output and cache counters remain independently reported volumes. Receipt imports read `metrics.usage`; `inputTokenDefinition` must be explicitly supplied by a caller with authoritative counter semantics. Provider name or compatibility with an API wire format does not establish those semantics.

The footer shows aggregate observed samples, their input definitions, and partial or complete lifecycle coverage. These are call volumes, not current context occupancy. A native Codex worker with no exposed usage has unknown counters; it contributes no fabricated zeros. Missing usage from other workers limits scope to the observed samples. The JSON preserves available counter sources in worker metadata.

Context metadata requires current tokens, capacity, served model, configuration, observation timestamp, validity interval, source, and reported or measured quality. The resolved binding must match that model and configuration. Expired or unmatched measurements yield unknown occupancy. Grok's catalog default is 256k with an optional 500k configuration; a catalog capacity alone does not supply occupancy. A one-million-token capacity is unverified. Native Codex context tokens and capacity are unavailable through this host's collaboration tools.

Workflow wall time, summed worker elapsed time, model duration, API duration, and tool duration have distinct meanings. Concurrent worker elapsed time can exceed wall time. These measurements are neither CPU time nor utilization percentages. There is no guessed token rate, idle time, paid waste, or capacity utilization. `briefBytes` measures UTF-8 bytes, never tokens. `fork_turns=none` records a control choice, not proven cache savings.
