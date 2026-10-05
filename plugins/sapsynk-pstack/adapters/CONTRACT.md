# Sapsynk pstack runtime contract

Read this contract before applying an upstream workflow. The complete pstack source remains authoritative for engineering decisions. This contract translates host mechanisms; it does not waive evidence, independence, isolation, review, or authorization requirements. A more specific user instruction or the host's permissions takes precedence.

## Start and resolve resources

Resolve the installed package root from the loaded skill's absolute path, or its skill-provider resource URI. Read the matching host adapter. Read project `.pstack/framework.lock.json` and `.pstack/config.json` when present; otherwise read this package's `config/defaults.json`. A project pin controls the release. Do not update it during a run.

Use the main `sapsynk-pstack` entry to load upstream `poteto-mode` and select its playbook. Most leaf skills are explicit-only and are read by the router; installation alone is not a standing project instruction. Project bootstrap and optional global host instructions provide persistence.

Resolve upstream skill names within THIS plugin. If another installed plugin exposes `architect`, `how`, or `poteto-mode`, do not accidentally route to a reduced ChatGPT adaptation. Resources, playbooks, personas, guides and original scripts are included relative to the installed root. `git show origin/main:pstack/...` means read the pinned framework artifact plus current project policy; it does not require duplicating pstack in application trunk. Upstream `~/.cursor/rules/pstack-models.mdc` references mean the portable role configuration on non-Cursor hosts.

## Role bindings

Preserve upstream role labels, panel entry count, budget intent, candidate independence and judging order. Configuration separates provider, transport, model and effort. Resolve a role once at the coordinator. Validate native model/effort against the actual spawn schema; `auto` or `inherit-parent` omits both overrides. A missing role uses an explicit inherited binding, not an unavailable hard-coded Cursor slug. Log the requested and resolved binding and any permitted fallback. Setup updates portable project/user configuration rather than writing a Cursor file on Codex.

Use the [setup adapter](setup-pstack.md) to materialize explicit bindings from the approved role layers and discovered capabilities. Grok is the preferred routine worker; a response-only lane cannot satisfy file requirements, and a narrow broker proof does not qualify arbitrary repository tests. Every Astra slot considers Sol 6.1/high before dispatch. Prefer Sol for bounded routine judgment and prose; use Astra when the task evaluation warrants its cost. Optional high and xhigh escalation remains available when evaluation and the discovered model schema support it. Record the chosen binding and reason. These policies do not switch the coordinator's model or waive panel independence.

A workflow requiring a different family remains unmet until that family's actual terminal receipt passes. Do not silently replace a failed provider or count an unavailable call as an agreeing vote. Use native children when the provider belongs to the coordinating host and its schema permits the selected model. Use the external-agent runtime for other providers.

## Host capabilities and delegation

Discover the host's actual tool map and runtime status. Do not pass Cursor-only parameters to Codex or Claude Code tools. Pass every worker the complete scoped brief, project pin, current user directives, verification contract, owned worktree/output path, and the full persona path. Fresh agents receive fresh consolidated briefs. Read-only review instructions are not an OS permission boundary. File/worktree isolation does not establish isolation of credentials, processes, ports or VMs.

Panels larger than runtime capacity run in waves with every requested candidate preserved. Distinct worktrees protect concurrent writers. If a playbook specifically requires independent VMs or ten simultaneous live lanes, waves in one container do not meet that requirement. Mark it unmet or use a real supported VM backend. Source coverage and operational parity are separate results.

Choose delegation from independent work units and required workflow panels, rather than a fixed agent count for every task. The [dispatch policy](dispatch-policy.md) sets the thresholds: trivial or read-only one-step work runs inline or in a cheap native subagent, workers and panels take substantial, parallel or independent-judgment work, and every skipped worker is logged and still verified. Candidate independence is checked, not assumed: each design seat gets its own lens and `pstack-run divergence` must pass before two candidates count as distinct. Use scoped briefs and resource pointers with fresh context instead of copying the whole conversation. Spare context capacity consumes no tokens by itself. Track repeated input, cache counters and coordination work where the host exposes them; do not optimize for filling a model's advertised window.

On a managed or shared host, run external CLI agents through `python3 <package>/runtime/cli.py run --project <project> --request <request.json>`. On an owner-controlled host without those restrictions, use the project's `scripts/pstack-run`, described in [the runtime guide](../runtime/README.md#local-worker-runner): one worktree, run directory and receipt per task. Use a persistent host terminal session and retain its handle. Inspect the final receipt and actual output before synthesis. Requests and logs live in independent private job directories. No implicit timeout limits a healthy model run; an explicit contract can supply a deadline. CLI/API credentials are configured outside source control. Preserve required cloud proxy/trust settings. Do not forward unrelated provider/GitHub credential variables. On-disk profile access still depends on the outer sandbox and is not secret isolation.

## Verification and dependent skills

The attributed `deslop`, `control-cli` and `control-ui` companion skills are bundled. Reuse project verification before constructing a new harness. Native browser/computer-use/PTY tools are the controls when available. Run real user paths and keep artifacts; tests or source inspection do not substitute for an unavailable surface. Cursor `create-skill` maps to the host's skill creator when available and native manifest/reference validation. The authoring playbook's structural checks remain required.

The bundled Bun/Node/Bash scripts remain unchanged. Install frozen runtime dependencies before invoking them; do not install dependencies into immutable plugin files. `orch` stores coordination facts; it does not schedule workers or establish merge authority. `watch-pr` is read-only and its READY output is not repository approval. Validate the current head, relevant verification evidence, approvals and explicit user merge authorization at the actual landing boundary. Graphite-dependent frontier operations require Graphite until a separately verified adapter is configured.

## Continuation and history

Cursor `/loop` maps to a supported scheduler/heartbeat on hosts that provide one. Discover its current schema; record the saved job and verify delivery before claiming unattended continuation. An exec process continues only while its environment survives. When scheduling is unavailable, finish attended work and write a resume capsule rather than promising future wakes.

Project-scoped history APIs or accessible event/transcript artifacts replace Cursor transcript paths. Never scan unrelated projects to infer ownership. Local job manifests and checkpoints need an approved durable branch/artifact/store to survive VM deletion. A replacement VM reads the project pin, installs that release and reconstructs completed work from the real artifacts. Old process and agent IDs are not durable handles.

## Optional Cursor integrations

Benny, make-bot-ui and Cursor event/routine integrations are retained in full and dormant. Their host bindings require their own setup and capability tests. Do not activate Slack/tracker writes, webhooks, polling, merge or deploy actions merely because a plugin was installed. Benny's credential/tool separation must be enforced; otherwise its coordinator does the work. Event delivery and polling have different latency semantics and must be labeled. See `automation.md`.

## Durable evidence

Retain request and actual model metadata, prompt/artifact digests, terminal outcome, current source/head identity, independently observed checks, skipped or unmet requirements, decisions and checkpoint references. Keep private prompts/logs out of Git by default. Commit sanitized evidence when the task calls for an auditable record. A failed, cancelled, timed-out or malformed CLI result is never VERIFIED.

Use [workflow metrics](workflow-metrics.md) for private lifecycle events and deterministic two-line snapshots on substantive coordinator outputs. Native agent events require coordinator instrumentation. Unobserved history, token counters and context occupancy remain unknown; cumulative token volume is not current context occupancy. A formatter cannot modify unrelated host or tool messages.
