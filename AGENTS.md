# Sapsynk pstack framework

Use pstack's poteto-mode and figure-it-out workflow for substantive work. The pristine upstream source is `upstream/pstack`; do not edit it. Read the relevant principles, skill, and playbook before applying them. Preserve workflow requirements and explicitly report capabilities that the host cannot provide.

Use `Boobesh P <builder@sapsynk.com>` for every commit. Do not override this identity unless the user explicitly requests it.

Generated plugin files belong in `plugins/sapsynk-pstack`; change their sources and rebuild instead of editing generated copies. Provider execution is owned by `runtime/`. Build and validation are owned by `tools/`. Portable interpretation and host mappings belong in `adapters/`. Keep model providers independent from agent hosts.

Verify the actual artifact and inspect delegated changes. An unavailable provider is not a successful reviewer. Never fabricate model, scheduling, permission, or isolation support. Credentials are configured outside this repository.
