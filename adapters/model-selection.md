# Portable setup selection and evidence contract

Setup-pstack detects supported combinations and confirms budget/roles using the existing host adapter. Use [verify-model-routing](../skills/verify-model-routing/SKILL.md) to validate availability and compare concrete options when authorized. Its helper is [runtime/model_selection.py](../runtime/model_selection.py). Reuse existing project artifact checks. This policy selects among measured model/effort/provider/transport/host/harness combinations for declared tasks. It is not a universal model capability benchmark.

The installed skill link above resolves within a built package. In a source checkout the skill is `extra-skills/verify-model-routing/SKILL.md`.

## Rubric

Freeze task definitions, acceptance checks and critical violations before gathering runs. Apply the same rubric to every option. The coordinator independently observes the returned artifact and real check output. Worker self-ratings earn no points.

| Criterion | Points | What earns the points |
| --- | ---: | --- |
| Correctness | 0 to 45 | Required behavior works on stated normal and edge cases. Award in proportion to predeclared assertions passed. |
| Scope | 0 to 20 | Artifact obeys allowed paths/interfaces, data handling and task boundaries. Award against predeclared scope checks. |
| Verification | 0 to 20 | Independently run the task's real artifact checks and observe their outcomes. Full points require the mapped user path where applicable. A response-only task earns points for the coordinator's local artifact tests, never invented provider-side tests. |
| Completeness | 0 to 15 | All required deliverables and named cases are present and usable. Award against the frozen deliverable list. |

Successful terminal execution and independently verified work are prerequisites for quality points. Failed/unverified attempts score zero and remain in the denominator. Per-task mean quality must be at least 85. Any critical scope/security/instruction violation disqualifies the option even when its artifact otherwise works. A task with inadequate checks produces inadequate evidence; numeric precision does not repair it.

## Record shape

The input is one JSON object with exactly `schemaVersion` 1, `evidenceKind` (`captured` or `unit-fixture`), `policy` and a nonempty `runs` array. `unit-fixture` is rejected by default; even `--allow-unit-fixtures` cannot choose an option or establish availability. `captured` means the coordinator actually inspected the authentic native run and artifact. Never relabel fabricated fixture data as captured evidence.

`policy` permits `incumbent` (candidate ID), `weights` (exactly `quality`, `latency`, `cost`, finite values 0 to 1 summing to 1), and `checklist`. Omitted weights use 0.70/0.15/0.15. Selection requires nonempty evidence statements for all seven checklist keys: `limiter`, `tuning`, `limits`, `errors`, `repeatability`, `relevance`, `workHappened`. Link the preserved observations in those statements. Name unknowns honestly; a guessed limiter does not satisfy the checklist. The helper checks presence, while the coordinator verifies the statements against evidence.

Each run requires exactly these fields, plus the listed optional fields.

| Field | Required value |
| --- | --- |
| `candidate` | Nonempty option ID, stable across repeats. |
| `model`, `provider`, `transport`, `host`, `harness` | Nonempty observed binding strings. Model is opaque and discovered from the actual provider. |
| `effort` | Nonempty observed effort string, or null when no override was sent. |
| `task`, `taskDigest` | Stable task ID and lowercase SHA-256 of the frozen task definition/check contract. |
| `repeat` | Positive integer, numbered 1 through N for each task and candidate. |
| `success`, `workVerified`, `criticalViolation` | Strict JSON booleans from the terminal receipt and independent observations. |
| `criteriaScores` | Exact keys `correctness`, `scope`, `verification`, `completeness`; finite numeric scores within 45/20/20/15. Zero scores when work is unverified. |
| `elapsedSeconds` | Positive finite elapsed time matching the terminal receipt. Same timing boundary for all options, including preflights/retries when the harness includes them. |
| `evidence` | Exactly `receiptPath`, `receiptSha256`, `artifactPath`, `artifactSha256`, `verificationPath`, `verificationSha256`. Paths resolve relative to the input file or are absolute. Each digest must match the preserved file. |
| `nativeCostUSD` | Optional finite nonnegative independently observed native measured dollar cost; omit/null when unknown. |
| `estimatedCostUSD` | Optional finite nonnegative estimate, labeled and excluded from selection. A subscription is not free measured per-run cost. |
| `tokens` | Optional object containing only nonnegative integer `input`, `output`, `total` counts. Usage tokens do not establish billed cost. |

One receipt file or receipt digest can count only once. Preserve native job/attempt identity in normalized receipts so repeated runs remain distinguishable. Missing fields, unknown run keys, NaN/infinity, bool-as-number, invalid score/duration/cost, duplicate attempts, changed bindings/tasks, hash mismatches and fabricated provenance fail validation. Preserve a failed run's receipt and its empty/partial artifact rather than dropping it.

The runtime receipt already supplies `provider`, `model`, `effort` (may be omitted for null), `transport`, `status`, `elapsedSeconds`, `authVerified` and `modelVerified`. Successful runs require `status` `complete` and true authenticated/model-verified evidence. Failure statuses are `failed`, `cancelled`, `timed-out`. Model identity must actually be verified by the host/provider; do not elevate pinned arguments to served-model evidence. Provider reports can use billing labels separately from served-model identity.

For a native host harness, save the original native events and a normalized receipt with these same fields, referencing the original evidence. Preserve actual identity verification. The helper does not parse every provider's raw protocol and does not establish native support for arbitrary models. The matching host adapter owns normalization and supported launch controls.

The independent `verificationPath` JSON contains `kind` `artifact-check`, `source` `independent-observation`, a nonempty `verifier` different from the candidate ID, matching `taskDigest`, `criteriaScores`, `workVerified`, `criticalViolation`, `receiptSha256` and `artifactSha256`. Include test commands/assertion counts and observed outcomes as additional evidence. If a run has `nativeCostUSD`, the check must match that value and contain `costSource` `native-measured`. CLI estimated costs belong only in `estimatedCostUSD`.

An evidence hash chain detects mutation and cross-file mismatches. It cannot prove truthfulness, independent execution, chronology, test adequacy or cost accounting. Inspect the actual run events, artifact and local checker transcript. Keep private evidence outside Git.

## Smoke and selection

`--mode smoke` requires at least one observation and reports availability for every recorded option. It never selects a winner. Failed or unverified attempts do not establish availability. Fixture mode reports `fixture-only`.

`--mode selection` requires at least two options and the identical task set, task digests and repeat counts. Each task needs at least five complete interleaved rounds, one attempt per option per round. Input order must represent the actual observed dispatch order, with repeat numbers in round order. Preserve independent chronology evidence; the helper can detect a non-interleaved recorded order but cannot detect a dishonest reorder. Match load/settings, timing boundaries and checker versions. Use the benchmark checklist before reporting a timing difference.

The report gives run/success counts, `terminalFailures`, `verificationFailures` (successful terminal responses without verified work), combined `outcomeFailures`, quality and elapsed median/range/mean, per-task quality and measured cost where all observations have it. The compatibility field `failures` counts terminal failures only. Failures count in latency and quality, so a fast rejection cannot win on speed. Only quality-eligible options enter utility comparison.

For each task, utility is `qualityWeight * meanQuality / 100 + latencyWeight * bestMedianLatency / optionMedianLatency + costWeight * bestMeanMeasuredCost / optionMeanMeasuredCost`. Average task utilities equally so an oversampled task cannot dominate. Both ratios are 1 when every comparable value is zero. Positive latency is mandatory. A zero cost weight skips cost entirely and makes no cost-benefit claim. With positive cost weight, unknown measured cost among eligible options makes selection inconclusive; estimates do not resolve it.

The report also averages per-task minimum/maximum per-run utilities into `utilityRange`, with ratios capped at 1 for individual attempts. If the best option's lower bound overlaps any other's upper bound, report inconclusive and preserve the incumbent. This is a conservative observed-variation check, not a confidence interval or statistical significance claim. A close choice needs more representative repeats or the harness's proper statistics. Unknown required cost, missing checklist evidence, unfair repeats or no eligible option also produce inconclusive results. All weights and thresholds are local policy choices, not learned capability scores.

A valid inconclusive report exits 0; invalid evidence exits 2. Inspect `verdict`, `selected`, `reasons`, `preserveIncumbent` and unmet runtime boundaries before updating routing. This helper never edits configuration, invokes providers, merges, publishes or changes role counts. Preserve the approved incumbent when evidence is insufficient.
