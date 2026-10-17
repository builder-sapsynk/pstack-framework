# Claude Code host adapter

Claude Code is a qualified coordinator. The same pstack skills, role labels and project configuration apply as on Codex. This file maps the mechanisms; [the contract](CONTRACT.md) still governs evidence, independence and authorization.

## Installation and pin

The plugin is `sapsynk-pstack@sapsynk`, served from this repository's `.claude-plugin/marketplace.json`. A project's `scripts/bootstrap-pstack --host claude-code` clones the exact locked revision to `~/.pstack/framework/<revision>` (override with `PSTACK_HOME`), validates it, registers that directory as the `sapsynk` marketplace and installs the plugin at user scope. Claude Code loads a directory marketplace in place, so that checkout is the active package and must stay unmodified. `scripts/bootstrap-pstack --check` compares its `framework.json` with the project lock.

The project commits `CLAUDE.md`, which imports `AGENTS.md`, and `.claude/settings.json`, which enables the plugin, sets the permission mode and runs the pin check at session start. A plugin installed during a session is available from the next session. Project settings and the session-start hook apply only after the owner has accepted Claude Code's trust dialog for the project once. One user installation serves one pin at a time; bootstrap again when switching to a project with a different pin.

Upstream leaf skills carry `disable-model-invocation: true` so a session does not load 54 descriptions. Read a leaf by path from the package root when the router or a playbook names it. `poteto-mode`, `setup-pstack` and the `sapsynk-pstack` entry stay model-invocable.

## Tool mapping

| pstack or Cursor mechanism | Claude Code |
| --- | --- |
| Task, named subagent | Agent tool. `sapsynk-pstack:pstack-worker` for a scoped writer in its own worktree, `sapsynk-pstack:poteto-agent` for the full persona, `Explore` for read-only search |
| Worktree per writer | `isolation: worktree` on the Agent call or agent definition |
| Todos | The session's task or todo tool |
| AskQuestion | AskUserQuestion, only for a real missing decision |
| `/loop`, wakeups | The host's loop and scheduling tools; verify delivery before claiming unattended continuation |
| Other providers | `pstack-run`, below |

Native model and effort follow the Agent tool's schema. `inherit-parent` omits both. Do not invent a Grok or GPT model for a native child.

## Dispatch

Resolve each role once from `.pstack/config.json`, then through `host_bindings.claude-code`:

- `claude` bindings with transport `claude-code` run as Claude CLI workers through the runner, at the exact model and effort the role names: `scripts/pstack-run run claude <task-id> <brief-file> --role "<role>"`.
- `claude` bindings with transport `native`, and `inherit-parent` aliases, run as native subagents. A native child takes only the models the Agent tool's schema offers.
- `grok` bindings run as Grok Build CLI workers.
- `codex` bindings run as Codex CLI workers. This includes transport `native`: a Codex-native child does not exist on this host, so the same model and effort run through the Codex CLI.

Decide the route first with the [dispatch policy](dispatch-policy.md): `scripts/pstack-run decide "<unit>" ...`. Trivial work runs inline, and a skipped worker is logged.

Write one scoped brief file per worker: goal, owned paths, exact resource pointers, verification command, and what to report. Then start every independent worker in a single message:

```sh
scripts/pstack-run run grok  <task-id> <brief-file> --role "bug-fix"
scripts/pstack-run run codex <task-id> <brief-file> --role "judgment and prose"
scripts/pstack-run run claude <task-id> <brief-file> --role "why investigators"
```

Run each command as its own background Bash task. It blocks until the worker reaches a terminal state, so the coordinator receives exactly one completion per worker. Launch native subagents in the same message. Do not poll.

`--role` takes model and effort from that role and refuses a role that does not name the provider. Without it the runner uses `host_bindings.claude-code.workers.<provider>`, where Codex defaults to Sol at high effort, the task-sensitive alternative to every Astra slot. `--model` and `--effort` override both. Record the binding you chose and why.

## Receipts

The last stdout line of each run is the receipt: `task_id`, `provider`, `state`, `exit_code`, `model`, `effort`, `session_id`, `attempt`, `cost_usd`, `duration_s`, `total_cost_usd`, `total_duration_s`, `summary`, `summary_truncated`, `last_message`, `error`, `cwd`, `branch`, `diffstat`. Read that line and `scripts/pstack-run diff <task-id>`. Open `.pstack/runs/<task-id>/events.jsonl` only to diagnose a failure.

`summary` holds the worker's final message up to 2000 characters. When `summary_truncated` is true, read the whole answer from the `last_message` path, `.pstack/runs/<task-id>/last-message.txt`. Reviewer findings are judged from that file, not from a cut summary.

`cost_usd` and `duration_s` describe the latest attempt. `total_cost_usd` and `total_duration_s` cover every attempt of the task, so a `resume` or `run --force` never hides what the earlier attempt spent. `status --full` lists each attempt under `attempts`, with its own state, usage, cost, duration and kept `last-message.<n>.txt`.

`state` is `succeeded` only when the CLI exited 0, reported a successful terminal event and returned a nonempty final message. `failed`, `killed`, `timeout`, `startup_timeout`, `stalled` and `lost` are never reviewer votes and never trigger a silent switch to another provider. Codex does not report cost; `cost_usd` stays null. A receipt proves the worker ran, not that its change is correct: inspect the diff and run the project verifier yourself.

Workers commit in `../.pstack-worktrees/<project>/<task-id>` on branch `pstack/<task-id>`. The coordinator integrates: `git merge --no-ff pstack/<task-id>` or a cherry-pick onto the feature branch (`scripts/pstack-run diff <task-id> --patch | git apply --index` also carries uncommitted leftovers), then `scripts/pstack-run clean <task-id> --force`. Follow up in the same session with `scripts/pstack-run resume <task-id> <brief-file>`; stop one with `scripts/pstack-run kill <task-id>`.

## Autonomy policy

This host is a dedicated machine the owner controls. Workers get full autonomy: no OS sandbox, no approval prompts, every tool, full network. Isolation is one Git worktree and branch per task. Worktrees do not isolate credentials, processes or ports.

| Worker | Mode |
| --- | --- |
| Codex CLI | `codex exec --dangerously-bypass-approvals-and-sandbox` |
| Grok Build CLI | `--permission-mode bypassPermissions --always-approve` |
| Claude CLI (`pstack-run run claude`) | `--dangerously-skip-permissions` |
| Native `pstack-worker` | inherits the session; the project sets `permissions.defaultMode: bypassPermissions` |

Hard guardrails, for every worker and the coordinator:

- A worker commits only on its own task branch in its own worktree. The coordinator integrates worker branches.
- No push to main, no merge of a pull request, no force-push. The owner's Grok Bot merges pull requests to main; agents never do.
- No deploy and no customer-facing message.
- No printing or copying of credentials.

The runner states these in every worker header and installs per-run `pre-commit` and `pre-push` Git hooks for the branch and push rules. A plugin agent cannot set its own permission mode, so the native worker's mode comes from the project's `.claude/settings.json`.

Claude Code created a native subagent's worktree from the default branch, not from the coordinator's feature HEAD. Name the base commit in a native worker's brief and have it fast-forward first, or use `scripts/pstack-run run claude`, whose worktree starts from `--base` or HEAD. Native worktrees live under `.claude/worktrees/` and are removed with `git worktree remove`.

## Panel independence

A panel seat counts only when its candidate was briefed alone and returned its own shape. Two models given one identical brief converge, so model diversity alone does not meet "two structurally distinct candidates".

- Give each architect or arena design seat its own brief file with a different `Lens:` line. Seat N takes entry N of `LENSES` in `runtime/panel_divergence.py`. No brief names another candidate's task id, run directory or answer.
- Ask each candidate to open its answer with a `Shape:` line naming its whole-shape design.
- After the receipts arrive, run `scripts/pstack-run divergence <task-id> <task-id> ...`. It fails on a missing or repeated lens, a failed receipt, a shared session, a brief that names another candidate, an equal declared shape, or answers whose vocabulary overlaps more than 0.6.
- On failure the requirement is unmet. Dispatch a fresh seat with the next unused lens and the converged shape named as excluded, then check again. Report the requirement as unmet if it still fails.
- The check is a floor. The cross-judge still states whether the candidates are whole-shape alternatives, and a "same shape" verdict is also unmet.

Panels that require a different model family are met only by real terminal receipts from that family. Independent VMs, Graphite and Cursor automations remain unmet unless a real backend is configured.
