# Codex adapter

Use the exposed collaboration tools for native delegation. Map Cursor Task to spawn_agent, retain the returned ID, then use the corresponding wait/message/stop tools. A named poteto-agent is its complete `agents/poteto-agent.md` instruction file loaded by a fresh child; Comment Sicko is `agents/comment-sicko.md`. Do not invent a subagent_type field. With overrides, obey the current fork/model schema. Map todos to the supported plan tool. Map AskQuestion to the supported user-input tool only for real missing preferences or information.

Codex model and reasoning_effort are separate fields. Native capabilities, concurrency and sandbox settings come from the active host. Default roles are configurable in `config/defaults.json` or project `.pstack/config.json`. For setup, discover supported combinations and write only verified selections. Do not manufacture Claude/Grok native model slugs.

Claude and Grok external workers use `runtime/cli.py`; launching another model is a terminal operation, not a native spawn pretending to be another provider. Run in a tool-managed persistent exec session, capture the initial job ID, retain the session, continue launching other candidates and drain all terminal outcomes before judging. In this host seven total concurrent agents share a filesystem; discover capacity again in other hosts.

The package's native marketplace and cloud plugin expose all upstream skills. Supported installation applies to new chats; a running chat may have a cached initial skill list. Use exact installed resource pointers instead of assuming newly published skills are already in that list. Global persistence uses an optional managed block in `~/.codex/AGENTS.md`. Project persistence uses committed AGENTS.md, lock/config and scripts/bootstrap-pstack. Preserve unrelated user instructions.

Use terminal tools for the bundled CLI controls and available browser/computer-use/project harnesses for UI controls. A real unavailable surface remains blocked. Discover scheduling tools rather than copying `/loop`; preserve user notification intent and stay quiet on unchanged monitors. A configured schedule is not a delivery test.

Use gh when no real native PR creation tool exists. Attach created/reviewed PRs through the host's attachment tool where required. Installing pstack and GitHub authentication do not authorize merges. Host rules for external messages, publishing and production writes continue to apply.
