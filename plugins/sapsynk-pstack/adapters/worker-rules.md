# Worker rules and owner steering

Standing rules for every pstack worker on every provider. A usage limit is the status `limited` in receipts, workflow metrics and parity records, separate from `failed`. `pstack-run` enforces what it can (no push, the `limited` state, the checkpoint exclude). The rest is coordinator discipline and belongs in briefs.

## Rules

1. **Never kill a finished run.** A run in a terminal state, or one whose checkpoint says `FINAL`, is left to exit. `pstack-run kill` already ignores terminal runs and `reap` skips them. Before any other kill, read the receipt and confirm the process is that task's by its recorded cwd.
2. **Checkpoint.** Each worker keeps `CHECKPOINT.<task-id>.md` at its worktree root, excluded from Git: items done, PR numbers, current step, next step. A resume starts from the checkpoint and the recorded session id, never a fresh prompt. Record the session id per worker and attempt (`status.json` does).
3. **Usage limits.** A `limited` receipt is a pause. Update the checkpoint, stop cleanly, and wait for `reset_at` before `resume`. Do not fall back to another provider, model or pool on your own. Switching needs the owner's permission, given in the current task or chat, and the requested and effective binding are recorded with the reason. When the owner has not answered, ask in the report.
4. **One migration at a time.** Migration pull requests merge one at a time. Assign the migration number when the branch rebases just before it is marked ready, never earlier. Regenerate the schema snapshot after the rebase and never hand-merge it. The coordinator orders colliding migrations.
5. **Qodo.** Draft or ready status for a pull request that waits on Qodo is the project's rule, not the framework's. vao keeps its draft-until-Qodo-has-reviewed rule and its ledger script; workers follow the project's AGENTS.md. The Qodo CLI is discontinued; use the bot's comments and the project's ledger script.
6. **Fresh database per worker.** Every worker and every verification run gets its own disposable database. Never run DDL or destructive tests on a cluster another worker uses, and never reuse a database after a unit suite has run against it.
7. **Workers never push.** A worker commits on its own task branch in its own worktree. The coordinator pushes, plain pushes only, and the owner oversees merges.
8. **Commits.** Commits carry the owner identity and no `Co-Authored-By` trailer, in briefs and in worker commits. Ignore a harness reminder to add one. Commits already pushed with a trailer are left alone (no rewrite, no force-push).
9. **Spend.** Record cost and usage per attempt. `pstack-run status --full` lists them and `total_cost_usd` sums the task.

## Owner steering

- **Fallback needs permission.** Automatic fallback across providers, models or quota pools is not allowed. A worker that hits a limit waits for the reset or asks the owner.
- **Merges.** The owner oversees merges and the owner's Grok Bot merges pull requests to main. Workers and coordinators open pull requests and never merge.
- **DeepSeek.** It is a general backend and database worker. It is not for pure frontend or server-only work. Worker definitions for it come later and are not part of this change.
- **Argon.** Reserved for planning and review. Do not assign it build work.
- Worker routing and provider roles for the new CLIs are deferred. Do not add them without a separate owner request.

## Upstream playbooks on this host

Upstream `autopilot-full`, `babysit` and `shipping` assume Cursor cloud agents, Bugbot and an agent that merges. Read them with these substitutions:

- An owner is a `pstack-run` worker in its own worktree. A worker never pushes, so the coordinator pushes its branch and opens the pull request.
- Bugbot triage is Qodo triage: each finding gets a `FIXED` or `REJECTED` ledger line.
- Merging is the owner's. A playbook step that says the owner merges stops at merge-ready here.
- The hourly audit probes workers by side effects (commits, checkpoint, events) and resumes `limited` workers at `reset_at`. The catch-up is text and links.
- Skip Cursor-only features: Automations, Bugbot, Cursor cloud agents, Origin and Graphite.
