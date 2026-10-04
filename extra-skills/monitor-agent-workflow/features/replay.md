# Replay retained evidence

Set `PSTACK_CUTOFF` to the captured ISO timestamp and keep the original event files.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW" --cutoff "$PSTACK_CUTOFF"
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW" --cutoff "$PSTACK_CUTOFF" --json
```

The first command returns exactly two lines. The second returns the corresponding observed snapshot. Repeated replay at the same cutoff returns the same accounting. Record and compare file digests before and after read-only replay. Verify workflow/event directories remain mode `0700` and event files mode `0600`.

Import the same original receipt twice, then compare counts and usage. Durable `job_id` and import event identities prevent duplicate attempts or counters. Different-clock start/end pairs remain unknown; concurrent worker elapsed totals may exceed workflow wall time. Preserve this evidence after deleting only proven disposable scratch from the drive.
