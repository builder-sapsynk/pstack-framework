# Release verification

## 0.2.0, Claude Code host — 2026-10-05

Host: owner-controlled Debian 13, Claude Code 2.1.289, Codex CLI 0.160.0, Grok Build 1.0.46.

128 framework tests pass, including fixture tests for the worker runner's lifecycle, watchdogs, kill, resume and permission flags, the Claude Code install path and the locked optional-plugin restore. `claude plugin validate` accepts the marketplace and the plugin. Claude Code lists 57 skills and 3 agents for `sapsynk-pstack@sapsynk`; Codex installs 0.2.0 from the same source and both `scripts/bootstrap-pstack --check` hosts verify.

One smoke run from the vao-1.1 project used a single brief for three parallel candidates: a native Claude subagent in a harness worktree, `pstack-run run codex` (gpt-6.1-sol, high, 32.0 s) and `pstack-run run grok --role "feature, refactoring"` (grok-4.7, medium, 23.4 s, 0.042 USD reported). Each ended `succeeded`, changed only the assigned file and ran the project docs verifier. `resume` was exercised live for Codex and Grok on a scratch repository, and one external Claude worker ran there.

Not verified: the named `sapsynk-pstack:pstack-worker` subagent in a live session, because the plugin was installed during the verifying session and agents load at session start; the run used a general-purpose subagent given the same persona file. Whether `disable-model-invocation` lowers session context was not measured. Grok has no OS sandbox on this lane. Codex reports no cost.

## 0.1.2 — 2026-10-03

Published private source: https://github.com/builder-sapsynk/pstack-framework. Project content pin: `6f8245cab6c13a9ff26e838016e7d42dea84d681`, semantic digest `3a8b44d405f7025e2e70cf43e6ba0d50daef0853677ad2fb1b71809b3e305f67`. Git refs and GitHub's commit API both verified this source publication and the requested commit identity.

Private personal cloud plugin: https://chatgpt.com/plugins/plugins_6ac0b2ee244881918f771e5b572f3d99, release `pluginrel_6ac0b7575f548191b5e3e5539b439d3a`. Metadata readback verified version 0.1.2. Native Codex installation and project startup pin checks passed.

41 framework tests pass. A fresh framework clone rebuilt the same semantic identity as the installed plugin. A fresh application checkout ran its bootstrap against the exact remote revision, installed the remote marketplace, and passed the installed identity check.

Both device login processes completed their actual credential exchanges. Live external Codex execution then authenticated successfully. An initial sandboxed tool invocation could not read a file because the outer sandbox hid Codex's reserved socket directory; approved host execution with the child's read-only sandbox retained resolved this. Job `a5b8c3593e434d67b486d7e72ea5a27f` successfully read the package identity, returned the correct name/version, and recorded command exit 0. Model evidence is pinned argv; the provider did not report a separate served model identity.

GitHub account repository creation still lacks the integration's Administration write grant; the account owner created the empty private repository, after which source push/readback succeeded. Existing repository Git, content and PR operations are available. Claude/Grok live authentication remains unverified. Protected credential setup is still required per fresh host; no cross-environment credential binding is claimed. Account cloud publication remains distinct from account installation, while native CLI installation is verified.

## Historical initial release: 0.1.0

Framework source commit: `d691f7030c921c021ca02a0d930c48fe33ce071d`.
Semantic digest: `66e2fa5bd15d5bf72f18a667039214ffe36251f3960cb681745c7ece5763f92c`.
Upstream source: Cursor plugins commit `23e4138daa01c42d4969f7a5465f82704e64f798`, pstack 0.15.6.

- Framework tests: 40 passed (9 packaging, 8 persistence, 23 runtime).
- Original upstream orch/watch-pr suite: 52 passed, 206 assertions; original strict TypeScript check passed. Dependencies and tests ran in a temporary copy, preserving pristine source.
- Artifact validation: all 160 original files, 49 upstream skills and 23 playbooks accounted for; 54 skills including companions. No introduced unresolved links. One placeholder `url` link already exists upstream.
- Native Codex installation: enabled plugin installed at the actual CODEX_HOME cache. Cached framework identity verified. Project startup content-pin check passed.
- Private personal cloud plugin created: `plugins_6ac0b2ee244881918f771e5b572f3d99`, release `pluginrel_6ac0b2f2682081918880b9b5dbab8bb5`. Readback confirmed manifest, framework digest and runtime source. Account publication is not proof of installation across chats.
- Current project instructions, pin, startup script and requested commit identity saved in a local application commit. Remote framework bootstrap depends on publishing the source repository.

## Unresolved operational requirements

GitHub repository creation returned `403 Resource not accessible by integration` through REST and GraphQL, including the explicitly selected saved GitHub CLI login after reported browser approval. Existing repository access and refs succeeded. The app's contents and pull_requests grants are write; administration is absent. No new framework GitHub repository or remote source commit has been published. Credentials cannot be added to managed cloud configuration with the available tools.

External Codex login preflight succeeded, but the actual bounded read-only execution failed: access token could not be refreshed because the session had logged out or changed accounts. Failed receipt and private provider events were retained; no successful external execution is claimed. Claude Code's reviewed CLI was installed outside the package, but authentication was unavailable; Grok Build executable and compatible structured-output dialect remain unavailable. Fixture tests establish adapter behavior, not live provider access.

No claim of complete cross-host functional equivalence is made. Cursor automation delivery, separate VMs, Graphite and optional integrations need real backing capabilities. Source and workflow preservation are verified; those services are not supplied by instructions alone.
