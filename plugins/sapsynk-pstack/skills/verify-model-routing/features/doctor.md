# Host and provider doctor

## Sub-features

- Discover the active native spawn schema and model/effort options.
- Inspect each installed external CLI and authentication preflight.
- Distinguish preflight readiness from successful live model work.
- Record unavailable tools, confinement and credential boundaries.

## How to get to it (user POV)

Invoke verify-model-routing during setup-pstack or before changing a binding. Resolve the current installed pin, package root, project and host adapter.

## Driving it with the runtime CLI

Run `python3 "$PSTACK_PACKAGE/runtime/cli.py" doctor --project "$PSTACK_PROJECT" --json`. Capture the JSON and terminal exit separately. Inspect individual provider statuses even when the aggregate exit is nonzero. Read the active host's actual tool schema. Compare configured bindings to discovered combinations. Preserve the observed statuses privately.

A working end state identifies which options are ready for a live probe and which are blocked, with their concrete reasons. It does not claim that doctor executed a task.

## Gotchas

An installed binary or cached login is not live execution proof. Native Codex discovery does not make Grok/Claude native models. Grok response-only readiness does not establish file sandboxing or writable isolation.

On a host that also runs Claude Code, this doctor reports Grok as `blocked: Grok inspect discovered unsupported plugins (...)`. Grok Build loads the user-scope plugins Claude Code installed, including pstack itself and the optional Sapsynk plugins, from `~/.claude/plugins`. Its `GROK_CLAUDE_*_ENABLED` switches cover skills, rules, agents, MCP servers and hooks but not plugins, and the request-file lane fails closed on any plugin. That is the intended verdict for the managed lane and it is not a Grok outage. On an owner-controlled Claude Code host the Grok lane is `scripts/pstack-run run grok`, so use `scripts/pstack-run doctor` for readiness and a `pstack-run` receipt as the live probe.
