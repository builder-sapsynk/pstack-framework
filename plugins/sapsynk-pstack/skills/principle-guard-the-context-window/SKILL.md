---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
disable-model-invocation: true
---

> Sapsynk host adapter: Read [the portable contract](../../adapters/CONTRACT.md) and the [Codex](../../adapters/codex.md) or [Claude Code](../../adapters/claude-code.md) mapping for the coordinating host before executing this workflow. Select the matching host adapter when running elsewhere; preserve the original requirements and report unavailable capabilities. Verify the pinned [framework identity](../../framework.json) before relying on this installation.

# Guard the Context Window

The context window is finite and non-renewable within a session. Every token should be worth its cost.

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.

**Pattern:**
- **Isolate large payloads.** Route verbose outputs, screenshots, and large documents to subagents. The main context gets summaries, not raw data.
- **Keep frequently used content inline.** Templates and references used on every invocation belong in the skill file, not in separate files that cost a read each time.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.
