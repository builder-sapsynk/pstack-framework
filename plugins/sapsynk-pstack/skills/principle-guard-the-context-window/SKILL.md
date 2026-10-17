---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
disable-model-invocation: true
---

> Sapsynk host adapter: Read [the portable contract](../../adapters/CONTRACT.md) and the [Codex](../../adapters/codex.md) or [Claude Code](../../adapters/claude-code.md) mapping for the coordinating host before executing this workflow. Select the matching host adapter when running elsewhere; preserve the original requirements and report unavailable capabilities. Verify the pinned [framework identity](../../framework.json) before relying on this installation.

# Guard the Context Window

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.

**Pattern:**
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.
