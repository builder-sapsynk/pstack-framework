# Poteto Mode in new chats

Version 0.1.3 makes Poteto Mode and setup-pstack discoverable entry skills. Their native metadata supplies display names, explicit invocation prompts and `allow_implicit_invocation: true`. The main Sapsynk router remains discoverable. Detailed workflows remain explicit-only and the router reads them as needed.

In 0.1.2, Poteto Mode was bundled but its native policy hid it from the model's default skill context. A user could still invoke it explicitly, or ask the main router to read it. Loading the plugin and adding a selectable skill are distinct operations.

After updating the installed private plugin, start a fresh chat and use the registered qualified skill name `$sapsynk-pstack:poteto-mode`, or select Poteto Mode when the client exposes it. The corresponding setup name is `$sapsynk-pstack:setup-pstack`. Standalone file skills can have unqualified names; the plugin loader adds its namespace. Plain `@poteto mode enable` is text unless the UI turns it into a real mention. It can still ask the agent to read the skill, but a confirmation sentence is not proof that it did.

The Windows chat titled Enable Sapsynk pstack was checked through its actual command history. It successfully read the main entry, the portable contract, Poteto Mode and the Codex adapter from its 0.1.2 private cache. Its chat folder is outside vao-1.1, so the repository's standing instructions and project role choices do not apply there.

The plugin request itself read Poteto before the later mode-enable message. That proves router activation in the affected chat. It does not prove independent picker visibility. This cloud conversation additionally received direct references to the original source skill files.

Codex's public terminal client groups plugin-owned skills under their plugin in the `@` search catalogue, while its `$` catalogue retains individual skills. This establishes a client-side grouping mechanism; it does not establish the exact implementation of the proprietary Windows desktop picker. A fresh native registry scan confirms 54 enabled namespaced skills. The user still reports the Windows picker missing after the account update, so that client-specific issue remains unresolved. Do not treat SDK registration as a UI fix.

Package defaults now reflect the operator's chosen Sol high, Astra medium and how explainer low settings, with token conservation. A project config can override those bindings. Availability and invocation arguments still require validation against the active host. Installation does not change the parent chat model.

The vao-1.1 framework pin stays at 0.1.2. The account plugin update does not silently upgrade that project. The original upstream skill bodies remain unchanged. SDK discovery checks can verify metadata and parser behavior; the client's actual skill picker must be checked separately before claiming UI visibility.
