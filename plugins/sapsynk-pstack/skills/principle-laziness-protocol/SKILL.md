---
name: principle-laziness-protocol
description: "Apply when refactoring, evaluating diff size, or tempted to add abstractions, layers, or signal threading. Bias toward deletion and the smallest change that solves the problem."
disable-model-invocation: true
---

> Sapsynk host adapter: Read [the portable contract](../../adapters/CONTRACT.md) and the [Codex](../../adapters/codex.md) or [Claude Code](../../adapters/claude-code.md) mapping for the coordinating host before executing this workflow. Select the matching host adapter when running elsewhere; preserve the original requirements and report unavailable capabilities. Verify the pinned [framework identity](../../framework.json) before relying on this installation.

# Laziness Protocol

- **Consolidate decisions.** Do not repeat the same choice in several places. Put it behind one source of truth and pass the result as a simple flag.
- **Minimize the diff.** Make the smallest change that solves the problem. Fewer lines beat "elegant" boilerplate.
