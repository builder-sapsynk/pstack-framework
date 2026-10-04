# Record worker lifecycle

Set the package, private workflow, worker ID, and attempt variables from the actual drive. Record request and start separately. For a child, supply its observed parent ID.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker "$PSTACK_WORKER" --attempt "$PSTACK_ATTEMPT" --parent-worker coordinator --event requested
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" record --workflow "$PSTACK_WORKFLOW" --worker "$PSTACK_WORKER" --attempt "$PSTACK_ATTEMPT" --event started
```

After actual completion, record `complete`; after an observed error, record `failed`. Record `cancellation-requested` before cancellation and `cancelled` only when confirmed. Save progress and harness stages through `progress`, `phase-start`, and `phase-end`, with `stage` and optional `phaseId` metadata.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW" --json
```

Inspect unique worker counts, attempt counts, failed attempts, open stages, observation age, and progress age. A poll is an observation, not progress. Preserve all failed attempts if a retry succeeds. For complete lifecycle coverage, provide an explicit complete descendant manifest and observe every attempt's request, start, and terminal outcome. Otherwise retain partial coverage.
