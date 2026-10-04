# Inspect resource counters

Import an original terminal receipt using its durable job ID.

```bash
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" import-receipt --workflow "$PSTACK_WORKFLOW" --receipt "$PSTACK_RECEIPT"
python3 "$PSTACK_PACKAGE/runtime/workflow_metrics.py" summary --workflow "$PSTACK_WORKFLOW" --json
```

Inspect `tokens`, `modelSeconds`, `toolSeconds`, and each worker's original numerical usage metadata. The importer selects `metrics.usage` and excludes duplicate `modelUsage` representations. Unknown input definitions produce unknown normalized input totals. An explicit `includes_cache` definition preserves input; `excludes_cache` adds separately known cache counters. Only authoritative counter semantics justify that declaration. Preserve last-call versus all-calls scope in metadata.

Native Codex usage and current context occupancy are unavailable through this host's collaboration tools. Keep them unknown. Report bytes as bytes, elapsed time as elapsed time, and provider duration independently from wall time. Catalog capacity or input/output/cache volume does not establish occupancy. Grok's default 256k and optional 500k capacities are configurations, not measured tokens in use.

For a unit proof, record a `usage` event with fixture-labeled source and quality. Mark its evidence as unit-only. Do not count the fixture as provider execution. Verify unknown, cache-inclusive, and cache-exclusive input definitions against literal expected totals before relying on a normalization path.
