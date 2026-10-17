# Sapsynk pstack framework

Use pstack's poteto-mode and figure-it-out workflow for substantive work. The pristine upstream source is `upstream/pstack`; do not edit it. Read the relevant principles, skill, and playbook before applying them. Preserve workflow requirements and explicitly report capabilities that the host cannot provide.

Use `Boobesh <builder@sapsynk.com>` for every commit. Do not override this identity unless the user explicitly requests it.

Generated plugin files belong in `plugins/sapsynk-pstack`; change their sources and rebuild instead of editing generated copies. Provider execution is owned by `runtime/`. Build and validation are owned by `tools/`. Portable interpretation and host mappings belong in `adapters/`. Host-native agent definitions belong in `host-agents/`. Keep model providers independent from agent hosts.

All providers use the same canonical project sources, documentation, framework configuration and verification recipes. Do not create Grok-specific project copies, framework forks or duplicate source caches for worker access. Use shared Git worktrees for concurrent edits, and point workers at the canonical resources directly. Private per-job session state and receipts are execution evidence, not a second project. Report unavailable host integrations explicitly rather than claiming tool parity from filesystem access alone.

The owner authorizes Grok to use this project's cloud environment and task-relevant resources, including recommended native tool integrations. Preserve this authorization in downstream setup and capability configuration. It is not limited to one worker invocation. Keep the managed host's enforced permissions, existing merge/deployment/customer-message gates and exclusions for unrelated credentials, private transcripts and caller data. Qualify each integration through actual use; connecting a model does not automatically grant it Codex app APIs.

Verify the actual artifact and inspect delegated changes. An unavailable provider is not a successful reviewer. Never fabricate model, scheduling, permission, or isolation support. Credentials are configured outside this repository.

## Ponytail, with pstack and poteto-mode (all agents)

Every agent, orchestrator and workers, loads ponytail together with pstack and poteto-mode. Vendored from DietrichGebert/ponytail @ 16352ac, plain markdown: `plugins-vendored/ponytail/`, skill at `.agents/skills/ponytail/SKILL.md`. Read it before writing code.
Smallest complete change: skip what is not needed; reuse what the repo has; then stdlib or platform; then an installed dependency; then the minimum new code, plus one small test for non-trivial logic. Never cut validation, error handling, security or accessibility.
The skill scopes itself: code-writing tasks yes; research, audit, verify, security, migration and performance tasks no.
pstack's no-workaround-comments rule wins: no `shortcut:` or `ponytail:` marker comments. Keep the worker report format.
