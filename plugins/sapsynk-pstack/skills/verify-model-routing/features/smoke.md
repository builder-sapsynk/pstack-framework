# Availability smoke

## Sub-features

- Run a bounded task through the discovered native or external transport.
- Independently check the returned artifact.
- Preserve real terminal failures and unsupported boundaries.
- Report availability without choosing a performance winner.

## How to get to it (user POV)

Invoke verify-model-routing after doctor. Choose one authorized task and one attempt for every proposed option. Freeze the acceptance checks. Use an unrelated synthetic task when project transfer is not authorized.

## Driving it with the runtime CLI and artifact checker

Use the SKILL.md Drive request and `runtime/cli.py run` command. Retain the emitted job ID, terminal receipt, original provider events and response. For response-only tasks, the coordinator writes the returned source artifact to its own scratch and runs local acceptance checks. Observe actual output and side effects. Record an independent hash-linked check with the numerical rubric.

Run `python3 "$PSTACK_PACKAGE/runtime/model_selection.py" --input "$PSTACK_RECORDS" --mode smoke --output "$PSTACK_SUMMARY"`. Confirm `verdict` is `availability-only`, `selected` is null, and only options with successful authenticated/model-verified execution plus independently verified work have availability true. Preserve proof after disposing of task-owned scratch.

## Gotchas

A model's self-report earns no points. Fast errors and empty responses do not establish availability. `unit-fixture` data cannot establish live access. A toy task can establish a path and local artifact behavior without establishing general coding capability.
