# Authentication diagnosis

Current outcome: the actual GitHub and Codex device flows completed. External Codex authenticated, and a file-read task succeeded after launching the bounded worker through approved host execution while retaining its own read-only sandbox. The new framework repository has been published after the account owner created it. The diagnosis below records the initial failure and explains why account permission, credential exchange and sandbox tool execution require separate checks. See [verification.md](verification.md) for current evidence.

Official references read on 2026-10-03:

- https://developers.openai.com/codex/auth — cached login, headless device authentication and credential storage.
- https://github.com/openai/codex/tree/main/codex-rs/login — CLI authentication implementation.
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow — browser approval followed by the initiating client's token exchange.
- https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user — repository creation endpoint and permission requirements.

## External Codex

The failed job's login status passed, but its actual model request failed with an account-reload/refresh error. CLI login status checks available cached authentication, not a real successful model request. In the inspected source, the exact error is raised when guarded auth reload is skipped because the expected account is unavailable or differs. It does not establish that the user personally logged out, and the CLI message alone cannot establish the initial request failure's cause.

The documented headless remedy is `codex login --device-auth`. The account owner must enter the emitted code on OpenAI's device page. The CLI must then finish exchanging and storing credentials. A chat permission response does not complete this website flow. Live execution must be retried after the terminal confirms completion.

Version 0.1.1 also fixes a distinct transport bug: CODEX_API_KEY and CODEX_ACCESS_TOKEN were removed by the provider credential filter. They are now preserved for Codex, while unrelated provider credentials are filtered. Neither variable was present during the original failure, so this bug is not claimed as its cause. Receipts now distinguish authPreflight from authVerified, which is set only after successful execution.

## GitHub

The current injected app credential grants contents and pull_requests write but lacks administration write. Existing repository access succeeds; repository creation fails with an integration permission error. Repository selection and the account owner's admin role do not expand the token's grants.

The previous scope-refresh process was no longer available after the environment changed. Browser approval could not therefore be treated as a verified token exchange. A fresh live CLI flow has been started; after website completion, require the terminal's success message, inspect safe scope information and test actual creation. Do not claim that the managed proxy substitutes credentials solely because two paths produced the same error.

## Persistence

Plugin cloud publication, native installation, provider login and cloud credential persistence are independent checks. Version 0.1.1 has 41 passing fixture/framework tests and readback-verified private publication; native content-pin verification passes. Website login exchanges and live provider execution remain pending. The managed cloud status currently reports no configured secret bindings. Cross-environment credentials require supported protected cloud configuration; no configuration mutation tool is available in this session. Never put credentials in the framework or application repositories.
