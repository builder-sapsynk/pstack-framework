# Sapsynk pstack

Portable pstack engineering workflows, with Codex hosting today and separate Claude Code and Grok Build process adapters. The upstream Cursor pstack 0.15.6 source is retained unchanged at commit `23e4138daa01c42d4969f7a5465f82704e64f798`: 160 files, 49 skills and 23 playbooks. Five additional skills supply the framework entry point, provider execution and control companions.

## Build and verify

```sh
python tools/build.py
python tools/validate.py
python -m unittest discover -s tests -q
```

The deterministic archive is `dist/sapsynk-pstack-0.1.3.zip`. The package includes portable Agent Plugins 1.0 metadata and native Codex and Claude compatibility manifests. `framework.json` records the exact semantic source digest; `parity.json` records original-file preservation and skill-body hashes.

## Install in Codex

```sh
python tools/install.py --local "$PWD" --global
```

This installs `sapsynk-pstack@sapsynk-pstack` through the native Codex plugin CLI and verifies the actual cached package. It preserves unrelated configuration. Global framework instructions use the runtime's `CODEX_HOME` when configured. Account cloud publication is a separate private plugin save; uploading does not prove account installation or provider authentication.

For a committed framework checkout, bind an application project to the exact revision:

```sh
python tools/bootstrap.py --project /absolute/application --local "$PWD" \
  --revision "$(git rev-parse HEAD)" --name 'Boobesh P' --email builder@sapsynk.com
```

Commit the generated project lock, instructions, router skill and `scripts/bootstrap-pstack`. In a fresh environment run that script to restore the exact revision, then run `scripts/bootstrap-pstack --check` before each task. Remote restoration requires the framework repository to exist and be accessible. One host has one active installed framework version: switching projects may require reinstalling the pinned version.

## External providers

Use `python runtime/cli.py doctor --project /absolute/application --json` before dispatch. Read [runtime/README.md](runtime/README.md) for request format, durable receipts, cancellation and isolation. Provider and model selection are independent of the agent host. Missing authentication, unsupported CLI dialects and unsuccessful terminal results fail explicitly; they never count as reviewer votes.

Claude Code's restricted CLI profile is implemented and fixture-tested; live Claude authentication has not been verified. Grok Build requires an explicitly reviewed structured-output dialect; the documented plain-output profile is insufficient to establish the result contract. Installing this plugin does not install provider CLIs or supply credentials. Native GPT reviewers are independent instances within one model family until real external provider runs succeed.

Cursor-hosted automation, separate VMs, Graphite-specific operations and optional service integrations require real host capabilities. Their original workflows remain present, but preserved instructions alone cannot provide those capabilities. See [adapters/CONTRACT.md](adapters/CONTRACT.md) and the host adapters for mappings and limits.

## GitHub authentication

Read [docs/github-auth.md](docs/github-auth.md) and run `python tools/github_auth_check.py --help`. Keep credentials outside the repository. Repository selection, user roles and credential permission grants are separate. The current cloud GitHub integration permits existing repository content and PR operations but repository creation has returned an Administration-permission error.

## Provenance

Original source is under `upstream/pstack`; changes belong in adapters, runtime, tooling or extra skills. Rebuild generated files instead of editing them. The MIT licenses and NOTICE preserve upstream and companion attribution. Use `Boobesh P <builder@sapsynk.com>` for commits.
