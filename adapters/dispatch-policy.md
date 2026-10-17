# Dispatch policy

Every unit of work takes one of four routes. The coordinator decides before dispatch, with the same rules on every host. `runtime/dispatch_policy.py` holds the rules and a test keeps this table equal to the code.

A CLI worker costs about 15k input tokens per turn before it reads its brief. That is the measured floor for a one-line prompt on this host family: Grok 14k, lean Codex 15k, lean Claude 15k. A one-line `wc -l` sent to a worker cost 36k tokens. Work smaller than the floor is cheaper inline.

## Routes

| Route | What runs it |
| --- | --- |
| `inline` | The coordinator, with its own tools |
| `native-subagent` | One cheap read-only native child (`Explore` on Claude Code), no worktree |
| `worker` | One `pstack-run` or native worker per independent unit, each in its own worktree |
| `panel` | Every seat the playbook names, as real receipts from the configured families |

## Rules

Rules run in this order and the first match wins.

1. `override`. The escape hatch. A named route with a written reason always wins and is logged as an override.
2. `required-panel`. A playbook or the owner requires a panel (architect, arena, interrogate, reflect, why). Keep every seat.
3. `independent-judgment`. A review or second opinion on work the coordinator wrote goes to a worker that is not the author.
4. `parallel`. Two or more independent units run as one worker each.
5. `risky`. A write that touches a guardrail, security, credentials or anything irreversible gets its own worktree and review, however small.
6. `trivial`. Work under every inline threshold runs inline.
7. `bulk-read`. Read-only work that only exceeds the token threshold, and stays under the subagent ceiling, goes to a cheap native subagent so the bulk stays out of the coordinator context.
8. `substantial`. Everything else is a worker.

## Thresholds

| Key | Value | Meaning |
| --- | --- | --- |
| `inline_max_steps` | `3` | Tool calls or commands the work needs |
| `inline_max_files` | `2` | Files edited |
| `inline_max_lines` | `30` | Lines changed |
| `inline_max_tokens` | `15000` | Tokens the work adds to the coordinator context |
| `inline_max_minutes` | `5` | Expected wall time |
| `subagent_max_tokens` | `60000` | Largest bulk read a cheap native subagent takes |
| `small_subject_lines` | `150` | A review subject at or under this size is small |
| `small_subject_effort` | `low` | Effort cap for a reviewer or panel seat on a small subject |
| `small_subject_timeout_s` | `300` | `--timeout` cap for that seat |

A project overrides a value in the `dispatch_policy` table of `.pstack/config.json`. An unknown key is an error. A small-subject cap never applies to a risky subject. The cap lowers effort and deadline only. It does not remove a seat or change the model family.

## Decide and log

```sh
scripts/pstack-run decide "count lines in guard" --read-only
scripts/pstack-run decide "fix guard evasions" --files 2 --lines 120 --risky
scripts/pstack-run decide "review 30-line fix" --judgment --subject-lines 30
scripts/pstack-run decide "owner wants a second model" --override worker --reason "owner asked"
```

The command prints the route, the rule, the facts and any caps, and appends the same line to `.pstack/state/dispatch.jsonl`. That private log is the record that a skipped worker was a decision. Estimate the facts honestly before the work. When the work outgrows its estimate, decide again with the real numbers.

## Inline work is still pstack work

Skipping a worker skips only the worker. The coordinator still does all of this.

- Work on a feature branch. No push to main, no merge, no force-push.
- Run the project verifier or the narrowest real check, and keep its output.
- State the evidence for every claim in the reply.
- Keep the decision line in the dispatch log.

Inline work never satisfies a panel seat or an independent review. Those need real receipts.

## Lean workers and briefs

`pstack-run` starts lean workers by default. Codex runs with `--disable plugins --disable apps`. Claude runs with `--strict-mcp-config --disable-slash-commands`. Grok runs with Cursor and Claude compatibility scanning off. Measured on a one-line prompt, this takes Claude from 34.8k to 15.3k tokens and Codex from 22.3k to 15.0k. Pass `--full-context` when a worker needs the host's skills or connectors.

A brief names the goal, owned paths, exact resource paths, the verification command and what to report. Point at files. Do not paste them. Name a leaf skill by its path under the package root, since a lean worker does not load the skill catalog.

## Worker rules and owner steering

[worker-rules.md](worker-rules.md) holds the standing worker rules (finished runs, checkpoints, usage limits, migrations, Qodo pull requests, databases, pushes) and the owner's routing steering. It applies to every provider and host.
