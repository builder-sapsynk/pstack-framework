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
