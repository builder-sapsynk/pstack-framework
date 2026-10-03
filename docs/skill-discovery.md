# Poteto Mode in new chats

Version 0.1.3 makes Poteto Mode and setup-pstack discoverable entry skills. Their native metadata supplies display names, explicit invocation prompts and `allow_implicit_invocation: true`. The main Sapsynk router remains discoverable. Detailed workflows remain explicit-only and the router reads them as needed.

In 0.1.2, Poteto Mode was bundled but its native policy hid it from the model's default skill context. A user could still invoke it explicitly, or ask the main router to read it. Loading the plugin and adding a selectable skill are distinct operations.

After updating the installed private plugin, start a fresh chat and use `$poteto-mode` or select Poteto Mode in the skill picker when the client exposes it. Plain `@poteto mode enable` is text unless the UI turns it into a real mention. It can still ask the agent to read the skill, but a confirmation sentence is not proof that it did.

The Windows chat titled Enable Sapsynk pstack was checked through its actual command history. It successfully read the main entry, the portable contract, Poteto Mode and the Codex adapter from its 0.1.2 private cache. Its chat folder is outside vao-1.1, so the repository's standing instructions and project role choices do not apply there.

Package defaults now reflect the operator's chosen Sol high, Astra medium and how explainer low settings, with token conservation. A project config can override those bindings. Availability and invocation arguments still require validation against the active host. Installation does not change the parent chat model.

The vao-1.1 framework pin stays at 0.1.2. The account plugin update does not silently upgrade that project. The original upstream skill bodies remain unchanged. SDK discovery checks can verify metadata and parser behavior; the client's actual skill picker must be checked separately before claiming UI visibility.
