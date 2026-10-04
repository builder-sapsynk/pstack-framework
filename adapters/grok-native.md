# Direct Grok workers

The official Grok Build CLI is the worker process. A broker is optional. Native tools can read, search, edit and run approved commands when the launch inherits a supported managed host sandbox. Authentication, model execution and filesystem enforcement are separate checks.

Official [sandbox documentation](https://docs.x.ai/build/features/sandbox) distinguishes tool permissions from operating-system restrictions. On this cloud, Grok's inner sandbox failed with `bwrap: setting up uid map: Read-only file system`; the Landlock probe returned ENOSYS. A direct native-tool drive subsequently edited a file, executed Python checks and observed denial of a write outside the host's writable filesystem. This establishes an observed outer boundary; it does not establish per-worker VM, process, network or credential isolation.

## Request

The restricted profile remains optional. Use `dialect` exactly `{"id":"grok-build-native-1","confinement":"managed-host"}` for that lane. Add `host_boundary` exactly `{"host":"codex-managed-exec","writable_roots":["/workspace","/tmp"],"read_only_probe":"/"}` only on this supported host after inspecting its active permissions. Do not copy this declaration to another host without verifying its policy. The runtime repeats a harmless denied-write canary before inference and refuses direct tools if it succeeds. One canary does not measure every path or network boundary. The coordinating host must launch the runtime through its managed execution tool and retain the tool result.

`read-only` removes edit tools. `isolated-write` requires a separate Git worktree or the existing explicit empty-scratch contract, with a writer lock. This isolates simultaneous file ownership; the operating-system boundary remains the host's shared writable roots. File instructions and post-run path checks do not create an OS restriction to a worktree.

`allowed_commands` is a list of exact literal commands, for example `python3 -m unittest discover -s tests -q`. Shell expressions, substitutions, pipes and wildcard permission syntax are rejected. Only those commands receive Bash grants. Read/Edit grants and the explicit native inventory are separate. Never grant always-approve, yolo or bypassPermissions. Grant relevant source access only after the user's authorization; credentials, private transcripts and caller data remain excluded.

The runtime uses a private per-job Grok home, an opaque symlink to existing OAuth, and disables compatibility scanners, memory, nested agents, web, media, workflow and MCP tools. It explicitly removes unsupported tools and verifies the observed inventory. Do not trust `--tools` alone: tested multi-name inputs unexpectedly restored defaults, while exact disallowed-tool filtering produced the required inventory. Raw native streams remain private.

Run `python3 runtime/cli.py run --request /absolute/request.json` through the managed host. `status`, `cancel` and `checkpoint` use the emitted durable job ID. Optional `workflow` selects the private metrics event directory. Preserve the host terminal handle and drain its output. A process exit of zero does not override a native error result.

## Persistence and follow-up

Successful receipts retain the private Grok home and native session ID. A new request can set `resume_job` to that completed job's absolute directory. The runtime validates project ownership, prior dialect, provider/model/cwd/mode and session UUID before invoking documented `--resume`. Each follow-up gets a new durable receipt; the session retains earlier context. Do not restore repository snapshots or reuse an active writer. Cancellation stops the runtime's process group, not a verified remote API job.

[Headless scripting](https://docs.x.ai/build/cli/headless-scripting) and [sessions](https://docs.x.ai/build/features/sessions) document persistent sessions. ACP (`grok agent stdio`) is an official option for live client/tool integration; it is not needed for ordinary terminal workers. This adapter does not make Grok callable through Codex's native `spawn_agent` schema. Pstack routes external provider jobs explicitly.

## Full native task profile

Use `dialect` exactly `{"id":"grok-build-native-task-1","confinement":"managed-host"}` when the user authorizes the full native lane. It is not a fallback from the restricted profile. The same managed-host boundary, private job home, writer lock, resume rules, and outer host launch apply. Keep `--permission-mode dontAsk` and `--sandbox off`. Do not pass `--always-approve`, `--yolo`, or `bypassPermissions`. Inner bwrap/Landlock remains unavailable; the managed host is the outer sandbox.

The request must include `capability_scope` from the runtime for the selected mode. That scope states official built-in tools are discovered rather than hardcoded, the terminal is autonomous, web fetch and web search are enabled, file creation/edit follows isolated-write, child agents are where-available, and user-authorized scope is distinct from tool enforcement. A trusted terminal can exceed the brief, including merge, push, and deploy, unless the host enforces those limits separately. Exact `allowed_commands` belong to the restricted profile; this lane does not pretend a Bash grant is that enforcement.

Do not copy project or framework sources into a worker cache. Read canonical paths inside the declared writable roots, including paths outside the worktree cwd. File-tool writes must stay in the assigned worktree. Those checks score the recorded tool call. They do not confine the terminal or a child agent. Leave credentials, private transcripts, and caller data out of the brief and the environment.

The worker header permits authorized native child agents and still forbids a framework router or delegation to another provider. Home config enables subagents and web fetch, enables native session memory, LSP and tool discovery where available, and keeps Cursor/Claude compatibility scanners, hooks, and MCP off. Argv does not pass `--no-subagents`, `--disable-web-search`, or a `--tools` allowlist. It uses the documented wildcard permission rule for all official native tools and removes file-edit tools in the optional read-only lane. This grants tool authority and is subject to launch approval by the outer host. Init `tools` is the trusted CLI inventory. MCP servers, `__` tool names, and tools that were disallowed fail the job. Tools that init does not list stay `unverified`. `observed-in-init` is not artifact verification.

The task parser accepts positive `usage.server_tool_use.web_search_requests` and `modelUsage.*.webSearchRequests` after normalize. Response-only and `grok-build-native-1` still reject them. Matched tool results may set `is_error` and may carry text, JSON, or a list. Session, model, unique call identity, and terminal ordering stay strict. Bundled agents under the trusted Grok home are accepted on this lane only. Project agents, hooks, plugins, and MCP are not.

## Qualify

Drive the packaged `verify-agent-parity` skill and inspect independent artifact checks. Promote read/edit/verify only for the tools, command policies and host actually exercised. Context occupancy remains unknown where the host does not expose it. Keep a response-only lane when no trusted filesystem boundary is available. A narrower MCP broker can be separately qualified where task-specific capability confinement is needed; do not introduce a host bridge merely to replace working native tools.

## Managed host approval limitation

The current host approval reviewer rejected the unrestricted task profile, including after the owner explicitly authorized full resource access. The stated reason was unrestricted terminal access to credentials, private data and destructive operations on a shared host. Do not bypass that rejection. A narrower native read/web/child probe passed with shell and file-edit tools removed. Direct file creation passed in a separate task probe, but its delegation permission failed; that run is not a full-profile success. Full task promotion requires an approved launch or an integration that routes tool execution through the host permission checks. ACP is the official CLI interface for host filesystem and terminal integration. Monitoring records behavior; it does not establish isolation or replace permission checks.
