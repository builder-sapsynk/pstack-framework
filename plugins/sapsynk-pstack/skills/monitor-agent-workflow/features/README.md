# Workflow monitoring feature map

These recipes exercise the existing Python CLI. They do not launch a provider or scheduler.

| Feature | Recipe | Acceptance evidence |
| --- | --- | --- |
| Native and runtime lifecycle | [Record worker lifecycle](lifecycle.md) | Actual IDs, terminal outcomes, failed attempts, descendant manifest, partial or complete coverage |
| Usage and context evidence | [Inspect resource counters](resources.md) | Raw numerical counters, input definition, independent cache counts, unknown occupancy when unsupported |
| Private snapshot replay | [Replay retained evidence](replay.md) | Fixed-cutoff JSON and two-line output, unchanged private event files, idempotent receipt import |

Keep executed unit proof distinct from original native observations and provider receipts. Tests can prove accounting behavior; only a real authorized worker drive proves live execution.
