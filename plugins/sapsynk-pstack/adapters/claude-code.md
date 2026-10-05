# Claude Code host adapter

Claude Code is a qualified coordinator. The same pstack skills, role labels and project configuration apply as on Codex. This file maps the mechanisms; [the contract](CONTRACT.md) still governs evidence, independence and authorization.

## Installation and pin

The plugin is `sapsynk-pstack@sapsynk`, served from this repository's `.claude-plugin/marketplace.json`. A project's `scripts/bootstrap-pstack --host claude-code` clones the exact locked revision to `~/.pstack/framework/<revision>` (override with `PSTACK_HOME`), validates it, registers that directory as the `sapsynk` marketplace and installs the plugin at user scope. Claude Code loads a directory marketplace in place, so that checkout is the active package and must stay unmodified. `scripts/bootstrap-pstack --check` compares its `framework.json` with the project lock.

The project commits `CLAUDE.md`, which imports `AGENTS.md`, and `.claude/settings.json`, which enables the plugin, allows the runner and runs the pin check at session start. A plugin installed during a session is available from the next session. Project settings and the session-start hook apply only after the owner has accepted Claude Code's trust dialog for the project once. One user installation serves one pin at a time; bootstrap again when switching to a project with a different pin.

Upstream leaf skills carry `disable-model-invocation: true` so a session does not load 49 descriptions. Read a leaf by path from the package root when the router or a playbook names it. `poteto-mode`, `setup-pstack` and the `sapsynk-pstack` entry stay model-invocable.

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

- `claude` bindings and `inherit-parent` aliases run as native subagents.
- `grok` bindings run as Grok Build CLI workers.
- `codex` bindings run as Codex CLI workers. This includes transport `native`: a Codex-native child does not exist on this host, so the same model and effort run through the Codex CLI.

Write one scoped brief file per worker: goal, owned paths, exact resource pointers, verification command, and what to report. Then start every independent worker in a single message:

```sh
scripts/pstack-run run grok  <task-id> <brief-file> --role "bug-fix"
scripts/pstack-run run codex <task-id> <brief-file> --role "judgment and prose"
```

Run each command as its own background Bash task. It blocks until the worker reaches a terminal state, so the coordinator receives exactly one completion per worker. Launch native subagents in the same message. Do not poll.

`--role` takes model and effort from that role and refuses a role that does not name the provider. Without it the runner uses `host_bindings.claude-code.workers.<provider>`, where Codex defaults to Sol at high effort, the task-sensitive alternative to every Astra slot. `--model` and `--effort` override both. Record the binding you chose and why.

## Receipts

The last stdout line of each run is the receipt: `task_id`, `provider`, `state`, `exit_code`, `model`, `effort`, `session_id`, `cost_usd`, `duration_s`, `summary`, `error`, `cwd`, `branch`, `diffstat`. Read that line and `scripts/pstack-run diff <task-id>`. Open `.pstack/runs/<task-id>/events.jsonl` only to diagnose a failure.

`state` is `succeeded` only when the CLI exited 0, reported a successful terminal event and returned a nonempty final message. `failed`, `killed`, `timeout`, `startup_timeout`, `stalled` and `lost` are never reviewer votes and never trigger a silent switch to another provider. Codex does not report cost; `cost_usd` stays null. A receipt proves the worker ran, not that its change is correct: inspect the diff and run the project verifier yourself.

Workers leave changes uncommitted in `../.pstack-worktrees/<project>/<task-id>` on branch `pstack/<task-id>`. Integrate with `scripts/pstack-run diff <task-id> --patch | git apply --index`, then `scripts/pstack-run clean <task-id> --force`. Follow up in the same session with `scripts/pstack-run resume <task-id> <brief-file>`; stop one with `scripts/pstack-run kill <task-id>`.

## Limits on this host

Codex runs in its own OS sandbox: writes stay in the worktree, network is off, and it cannot commit because the worktree's Git metadata is outside the sandbox. Grok Build runs with `--permission-mode auto` and no OS sandbox; its worktree is file ownership, not confinement. Its headless `dontAsk` mode and its inner sandbox both cancel every terminal command here. The external Claude profile uses `acceptEdits` with a fixed tool list. No worker receives bypass or always-approve flags. Worktrees do not isolate credentials, processes or ports.

Claude Code created a native subagent's worktree from the default branch, not from the coordinator's feature HEAD. Name the base commit in a native worker's brief and have it fast-forward first, or use `scripts/pstack-run run claude`, whose worktree starts from `--base` or HEAD. Native worktrees live under `.claude/worktrees/` and are removed with `git worktree remove`.

Panels that require a different model family are met only by real terminal receipts from that family. Independent VMs, Graphite and Cursor automations remain unmet unless a real backend is configured.
