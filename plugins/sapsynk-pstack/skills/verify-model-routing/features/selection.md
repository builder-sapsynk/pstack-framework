# Balanced option selection

## Sub-features

- Freeze task definitions, quality checks, critical violations and weights.
- Gather at least five interleaved repeats per option for every task.
- Include failures in the quality and timing denominators.
- Gate quality before comparing weighted latency/cost utility.
- Preserve the incumbent when repeatability, variation or accounting is unresolved.

## How to get to it (user POV)

Invoke verify-model-routing when setup-pstack needs evidence to choose an option. Keep the approved role table and incumbent until the comparison supports a change. Choose tasks representative of the role rather than a project-specific hard-coded table.

## Driving it with the runtime CLI and model_selection.py

Launch one attempt per option in each numbered round, alternating options on the same frozen tasks. Retain actual chronology and every terminal outcome. Use the same independently executed artifact checks and timing boundary. Answer all seven benchmark checklist items with saved evidence.

Run `python3 "$PSTACK_PACKAGE/runtime/model_selection.py" --input "$PSTACK_RECORDS" --mode selection --output "$PSTACK_SUMMARY"`. Inspect counts, per-task mean quality, critical violations, quality/latency median and range, measured or unknown cost, weights and utility variation. A mean quality below 85 for any task or a critical violation makes that option ineligible. Default positive cost weight requires known measured cost. Zero cost weight must be explicitly declared and makes no cost claim.

Confirm `selected` appears only when fair repeat/checklist gates pass and the utility gap exceeds observed variation. Otherwise confirm `verdict` `inconclusive`, `selected` null and `preserveIncumbent` true. Preserve original receipts/checks/summary after cleanup. Apply changes only within already authorized setup scope.

## Gotchas

Reordering a list does not prove real interleaving. Estimated dollar amounts or subscription quota do not prove measured billed cost. A missing limiter makes a timing claim inconclusive. Overlapping observed utility ranges do not support a winner. Five repetitions of one toy task do not rank frontier models or replace representative task coverage.
