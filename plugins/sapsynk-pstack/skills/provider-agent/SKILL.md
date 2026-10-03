---
name: provider-agent
description: Run Claude Code, Grok Build, or Codex CLI agents as explicit external tools with isolated writer workspaces, model/effort bindings, durable receipts, cancellation and verified final output.
---

# External provider agent

Read `../../adapters/CONTRACT.md` and run `python3 ../../runtime/cli.py doctor --project <project> --json` using absolute resolved paths. An executable's presence is not successful authentication or model execution.

Write a bounded request JSON containing provider, model, optional effort, mode (`read-only` or `isolated-write`), cwd, and prompt_file. A writer owns a distinct Git worktree. The complete brief includes the project pin, user directives, allowed paths, artifact location and verification contract. Do not ask the child to choose a different provider or spawn recursive workers.

Invoke `python3 <package>/runtime/cli.py run --project <project> --request <request.json>` in a persistent host terminal session. Retain its session handle and initial job ID. Start independent candidates before waiting. Use the runtime's status/cancel commands and the host's terminal lifecycle. A timeout is optional and must come from an explicit task bound.

Read every terminal receipt and nonempty result. Confirm the selected provider, model evidence and successful normalized outcome. An exit-zero process without a valid final result is incomplete. Keep unverified model identity labeled; do not invent a reported model. Native and external candidates finish before a judge reads their artifacts.

Provider credentials stay in supported secret settings or authenticated CLI profiles. Do not paste credentials into requests, prompts, source control or receipts. External agents remain subject to the outer sandbox and their CLI's supported permissions. Missing credentials, unsupported flags, failed output, cancellation and unmet isolation are explicit unavailable/failed lanes; never substitute another provider silently.
