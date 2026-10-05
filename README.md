# Sapsynk pstack

Portable pstack engineering workflows for Codex and Claude Code hosts, with Codex, Grok Build and Claude Code CLI workers. The upstream Cursor pstack 0.15.6 source is retained unchanged at commit `23e4138daa01c42d4969f7a5465f82704e64f798`: 160 files, 49 skills and 23 playbooks. Additional skills supply portable setup, provider execution, verification and control companions.

## Build and verify

```sh
python tools/build.py
python tools/validate.py
python -m unittest discover -s tests -q
```

The deterministic archive is `dist/sapsynk-pstack-0.2.0.zip`. The package includes portable Agent Plugins 1.0 metadata and native Codex and Claude compatibility manifests. `framework.json` records the exact semantic source digest; `parity.json` records original-file preservation and skill-body hashes.

## Install in Codex

```sh
python tools/install.py --local "$PWD" --global
```

This installs `sapsynk-pstack@sapsynk-pstack` through the native Codex plugin CLI and verifies the actual cached package. It preserves unrelated configuration. Global framework instructions use the runtime's `CODEX_HOME` when configured. Account cloud publication is a separate private plugin save; uploading does not prove account installation or provider authentication.

## Install in Claude Code

```sh
python tools/install.py --host claude-code --local "$PWD"
```

This registers the checkout as the `sapsynk` directory marketplace and installs `sapsynk-pstack@sapsynk` at user scope. Claude Code loads that directory in place, so install from a clean checkout of the revision you intend to run. Projects normally do this through their own `scripts/bootstrap-pstack --host claude-code`, which uses a pinned checkout under `~/.pstack/framework/`. The plugin adds the skills, the `pstack-worker` subagent and `pstack-run`. Read [the Claude Code adapter](adapters/claude-code.md) for dispatch and receipts.

For a committed framework checkout, bind an application project to the exact revision:

```sh
python tools/bootstrap.py --project /absolute/application --local "$PWD" \
  --revision "$(git rev-parse HEAD)" --host claude-code --host codex --name 'Boobesh' --email builder@sapsynk.com
```

Commit the generated project lock, `AGENTS.md` and `CLAUDE.md` blocks, `.claude/settings.json`, router skill, `scripts/bootstrap-pstack` and `scripts/pstack-run`. In a fresh environment run that script to restore the exact revision, then run `scripts/bootstrap-pstack --check` before each task. Remote restoration requires the framework repository to exist and be accessible. One host has one active installed framework version: switching projects may require reinstalling the pinned version.

## External providers

Use `python runtime/cli.py doctor --project /absolute/application --json` before dispatch. Read [runtime/README.md](runtime/README.md) for request format, durable receipts, cancellation and isolation. Provider and model selection are independent of the agent host. Missing authentication, unsupported CLI dialects and unsuccessful terminal results fail explicitly; they never count as reviewer votes.

On an owner-controlled host, `scripts/pstack-run run <codex|grok|claude> <task-id> <brief-file>` is the worker path: a worktree, event log, `status.json` receipt, watchdogs, `resume` and `kill` per task. See [the local worker runner](runtime/README.md#local-worker-runner). The request-file runtime remains the path for managed cloud hosts, where Grok Build requires an explicitly reviewed dialect and host-boundary declaration. Installing this plugin does not install provider CLIs or supply credentials. Native GPT reviewers are independent instances within one model family until real external provider runs succeed.

Cursor-hosted automation, separate VMs, Graphite-specific operations and optional service integrations require real host capabilities. Their original workflows remain present, but preserved instructions alone cannot provide those capabilities. See [adapters/CONTRACT.md](adapters/CONTRACT.md) and the host adapters for mappings and limits.

## GitHub authentication

Read [docs/github-auth.md](docs/github-auth.md) and run `python tools/github_auth_check.py --help`. Keep credentials outside the repository. Repository selection, user roles and credential permission grants are separate. The current cloud GitHub integration permits existing repository content and PR operations but repository creation has returned an Administration-permission error.

## Provenance

Original source is under `upstream/pstack`; changes belong in adapters, runtime, tooling or extra skills. Rebuild generated files instead of editing them. The MIT licenses and NOTICE preserve upstream and companion attribution. Use `Boobesh <builder@sapsynk.com>` for commits.

## Model and effort validation

Use the packaged `verify-model-routing` skill before changing `setup-pstack` roles. It separates availability smoke checks from repeated model/effort comparisons and preserves failures in the evidence. See [model selection](adapters/model-selection.md). Grok Build supports a bounded response-only worker where native filesystem sandboxing is unavailable. The coordinator reviews and applies returned artifacts; this mode does not provide direct file tools or isolated writing.

The [setup adapter](adapters/setup-pstack.md) keeps the seven original setup steps and materializes a complete, reviewable role plan. Grok low/medium/high are the preferred exploration/routine/performance layers. Every Astra role considers Sol 6.1/high according to task requirements and cost. High and xhigh remain optional evaluated escalations. Capability gates are visible before configuration changes; failed providers never trigger silent substitutions.

Use `monitor-agent-workflow` and [workflow metrics](adapters/workflow-metrics.md) for deterministic agent counts, timing, token volumes and context observations. Missing host measurements stay unknown. Scoped briefs reduce duplicated context while independent panels retain their required members.

Direct native Grok tools use the explicitly qualified [managed-host adapter](adapters/grok-native.md). The runtime preserves per-job receipts, status, cancellation and resumable sessions. Use `verify-agent-parity` to distinguish functional tools from host/API/isolation limits. An MCP or command bridge is unnecessary when the managed host boundary and native tools pass the actual task checks.
