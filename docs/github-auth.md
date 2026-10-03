# GitHub terminal authentication

Run the read-only preflight in each new environment:

```sh
python3 tools/github_auth_check.py --project /path/to/project --repo owner/repository
```

It checks authentication, the user's repository role, visible application grants,
and the project's `builder@sapsynk.com` commit email. It prints no credential
values and changes no configuration. Run it with the environment's approved
network access; a sandbox network failure can otherwise look like invalid auth.
Repository creation remains unverified until an authorized create operation
succeeds. Reading a repository or authenticating successfully does not prove
creation, push, PR, or merge capability. Each operation also depends on branch
rules and its required token permissions.

## Credential selection

For github.com, GitHub CLI prefers `GH_TOKEN`, then `GITHUB_TOKEN`, then its stored
credentials. `gh auth git-credential` follows the same selection. Device login
can save a credential successfully while an injected environment token remains
the credential used by terminal commands. To inspect the saved credential with
the normal managed network path:

```sh
env -u GH_TOKEN -u GITHUB_TOKEN gh auth status
env -u GH_TOKEN -u GITHUB_TOKEN gh api user --jq .login
```

A managed outbound proxy can still apply the configured GitHub integration
identity. A saved token's prefix, browser success page, or OAuth scopes alone
cannot establish which permissions the API ultimately enforces. Preserve the
environment's proxy and trust configuration.

## The observed creation failure

Both credential paths authenticated as `builder-sapsynk`. The personal and
organization installations selected all repositories and granted contents,
pull requests, issues, actions, and workflows write access, plus checks,
statuses, and metadata read access. They did not list Administration write.
Personal and organization repository creation returned HTTP 403, “Resource not
accessible by integration.” Administration write is required by GitHub's create
repository endpoints when using application or fine-grained credentials.
Existing repository user role `admin: true` does not add that token grant.

This explains how an integration can support existing repository operations
while being unable to create repositories. Selecting all repositories broadens
repository coverage; it does not add missing application permissions.

## Durable setup

An application permission change must be supported by the application's owner;
the account installation cannot add a permission the application never requests.
An independently authorized GitHub CLI credential is another option, subject to
the managed environment's supported outbound authentication. Request the
required OAuth scopes, complete GitHub's device approval, then verify the actual
operation rather than assuming the new credential bypasses integration limits:

```sh
env -u GH_TOKEN -u GITHUB_TOKEN gh auth refresh --hostname github.com --scopes repo,workflow
```

Never commit tokens or paste them into chat. Stored CLI credentials in one VM do
not establish persistence in a new VM. Configure a protected secret binding and
supported startup credential selection in the cloud environment settings, then
verify it in a fresh environment. The available environment status tool can
inspect readiness; it cannot create secret bindings or change startup policy.
Keep the GitHub connection's permissions and terminal credential readiness as
separate checks. Project commit identity is independent of authentication and
is restored by this framework's project bootstrap.

## Device approval must finish in the terminal

GitHub's device flow has three steps: request codes, user approval in the browser,
and the application polling the token endpoint to obtain the credential. A browser
success page proves approval; it does not prove the CLI received or saved the new
token. Keep the initiating CLI process alive until it reports completion. If the
VM restarted or that process exited before exchange, inspect the current saved
credential readiness and start a new coordinated flow when the original code
cannot be recovered or has expired. GitHub device codes expire after 900 seconds.
Do not start simultaneous flows, or treat approval of an old code as approval of
the currently running flow.

A newly completed CLI authorization can solve missing OAuth scopes when that
credential is the effective outbound identity. It cannot itself enlarge another
application's permission grant or prove that a managed proxy uses the new token.
Verify the actual authorized repository creation operation after completion.

## Official references

Read against GitHub's current documentation on 2026-10-03:

- [Create a repository for the authenticated user](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user): classic OAuth requires `public_repo` or `repo` for public creation, and `repo` for private creation.
- [GitHub App Administration permission endpoints](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps#repository-permissions-for-administration): authenticated-user and organization repository creation require repository Administration write; endpoint-specific additional permissions may apply.
- [Choosing GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/choosing-permissions-for-a-github-app): the app and user grants both constrain user access tokens; app owners or managers change requested permissions and installation owners approve the change.
- [OAuth device flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow): the application must poll for and receive the access token after browser approval, within the device code's validity period.
