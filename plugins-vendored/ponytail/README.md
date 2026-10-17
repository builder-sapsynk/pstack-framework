# Vendored ponytail (plain markdown only)

Source: https://github.com/DietrichGebert/ponytail, pinned to commit `16352ac` (v5.3.2), MIT (see LICENSE).
Contains only prose: `AGENTS.md` (always-on rules) and one skill, `skills/ponytail`.
No hooks, no plugin manifest, no band/board, no webhook, no node code. Not an installable plugin; it is a source folder.
Skipped on purpose: `ponytail-review`, `ponytail-audit`, `ponytail-debt` (exists only to harvest `shortcut:` comments), `ponytail-gain`, `ponytail-help`, commands/, hooks/.

## Local changes vs upstream
- Removed every `shortcut:` comment instruction. The marker convention is dropped, not just overridden.
- `ponytail/SKILL.md`: replaced the "active for the whole session / /ponytail levels" line with a task-scoped statement.
- Appended a "pstack overrides" section (no-workaround comments win, scope by task class, keep worker report format).

## Load and scope
Loaded by every agent (orchestrator and workers) together with pstack and poteto-mode. The skill itself scopes where it applies:
code-writing tasks yes; research, audit, verify, security, migration and performance tasks no.

## Symlinks
`.agents/skills/ponytail` -> `plugins-vendored/ponytail/skills/ponytail` (dsh, opencode, agy read `.agents/skills`);
`.claude/skills/ponytail` -> `.agents/skills/ponytail`. One real copy only. `tests/test_ponytail_vendor.py` checks they resolve.
To update: re-vendor, re-apply the local changes above, re-pin the commit.
