# Direct Grok workers

The official Grok Build CLI is the worker process. A broker is optional. Native tools can read, search, edit and run approved commands when the launch inherits a supported managed host sandbox. Authentication, model execution and filesystem enforcement are separate checks.

Official [sandbox documentation](https://docs.x.ai/build/features/sandbox) distinguishes tool permissions from operating-system restrictions. On this cloud, Grok's inner sandbox failed with `bwrap: setting up uid map: Read-only file system`; the Landlock probe returned ENOSYS. A direct native-tool drive subsequently edited a file, executed Python checks and observed denial of a write outside the host's writable filesystem. This establishes an observed outer boundary; it does not establish per-worker VM, process, network or credential isolation.

## Request

Use `dialect` exactly `{"id":"grok-build-native-1","confinement":"managed-host"}`. Add `host_boundary` exactly `{"host":"codex-managed-exec","writable_roots":["/workspace","/tmp"],"read_only_probe":"/"}` only on this supported host after inspecting its active permissions. Do not copy this declaration to another host without verifying its policy. The runtime repeats a harmless denied-write canary before inference and refuses direct tools if it succeeds. One canary does not measure every path or network boundary. The coordinating host must launch the runtime through its managed execution tool and retain the tool result.

`read-only` removes edit tools. `isolated-write` requires a separate Git worktree or the existing explicit empty-scratch contract, with a writer lock. This isolates simultaneous file ownership; the operating-system boundary remains the host's shared writable roots. File instructions and post-run path checks do not create an OS restriction to a worktree.

`allowed_commands` is a list of exact literal commands, for example `python3 -m unittest discover -s tests -q`. Shell expressions, substitutions, pipes and wildcard permission syntax are rejected. Only those commands receive Bash grants. Read/Edit grants and the explicit native inventory are separate. Never grant always-approve, yolo or bypassPermissions. Grant relevant source access only after the user's authorization; credentials, private transcripts and caller data remain excluded.

The runtime uses a private per-job Grok home, an opaque symlink to existing OAuth, and disables compatibility scanners, memory, nested agents, web, media, workflow and MCP tools. It explicitly removes unsupported tools and verifies the observed inventory. Do not trust `--tools` alone: tested multi-name inputs unexpectedly restored defaults, while exact disallowed-tool filtering produced the required inventory. Raw native streams remain private.

Run `python3 runtime/cli.py run --request /absolute/request.json` through the managed host. `status`, `cancel` and `checkpoint` use the emitted durable job ID. Optional `workflow` selects the private metrics event directory. Preserve the host terminal handle and drain its output. A process exit of zero does not override a native error result.

## Persistence and follow-up

Successful receipts retain the private Grok home and native session ID. A new request can set `resume_job` to that completed job's absolute directory. The runtime validates project ownership, prior dialect, provider/model/cwd/mode and session UUID before invoking documented `--resume`. Each follow-up gets a new durable receipt; the session retains earlier context. Do not restore repository snapshots or reuse an active writer. Cancellation stops the runtime's process group, not a verified remote API job.

[Headless scripting](https://docs.x.ai/build/cli/headless-scripting) and [sessions](https://docs.x.ai/build/features/sessions) document persistent sessions. ACP (`grok agent stdio`) is an official option for live client/tool integration; it is not needed for ordinary terminal workers. This adapter does not make Grok callable through Codex's native `spawn_agent` schema. Pstack routes external provider jobs explicitly.

## Qualify

Drive the packaged `verify-agent-parity` skill and inspect independent artifact checks. Promote read/edit/verify only for the tools, command policies and host actually exercised. Context occupancy remains unknown where the host does not expose it. Keep a response-only lane when no trusted filesystem boundary is available. A narrower MCP broker can be separately qualified where task-specific capability confinement is needed; do not introduce a host bridge merely to replace working native tools.
