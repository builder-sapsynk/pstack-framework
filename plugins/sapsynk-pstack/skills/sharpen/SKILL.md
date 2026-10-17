---
name: sharpen
description: "Sharpen a task before starting: the expert approach, what the user is really after, and the right level of specification. Use for /sharpen."
disable-model-invocation: true
---

> Sapsynk host adapter: Read [the portable contract](../../adapters/CONTRACT.md) and the [Codex](../../adapters/codex.md) or [Claude Code](../../adapters/claude-code.md) mapping for the coordinating host before executing this workflow. Select the matching host adapter when running elsewhere; preserve the original requirements and report unavailable capabilities. Verify the pinned [framework identity](../../framework.json) before relying on this installation.

Before starting, ask how a top expert would approach this task (their raw sources, their real methods, an outside check that the result is right), what the user is really after, and whether the task is over- or underspecified. Loosen constraints that don't serve the goal as readily as you add ones that do, and leave choices that are the user's to make open instead of deciding them. Fold in only what makes the work better, not bigger, but always keep one outside check that the result is right, without narrating the framing, then do the work. Don't hand back a rewritten prompt.
