# Design and execution contract

The user requested a complete Sapsynk distribution of pstack for Codex cloud, with external Claude Code and Grok Build agents and future coordinator-host portability. The original source is pinned at Cursor commit `23e4138daa01c42d4969f7a5465f82704e64f798`, pstack 0.15.6.

## Done predicate

All 160 original files remain byte-identical and are accounted for in the source lock. The installed distribution includes all 49 upstream skills, 23 playbooks, both personas, references, helpers, and dormant automation. Native packaging and local resources validate. External CLI launches preserve the requested provider/model/effort, produce durable per-job receipts, never turn failed calls into votes, and support cancellation. Installation/bootstrap is idempotent and preserves a project's exact release and commit identity. GitHub and private cloud publication are verified independently. Live provider and scheduler claims require real authenticated execution; missing access remains an explicit blocker.

## Alternatives and synthesis

Two independent pstack architect candidates were evaluated. Candidate A used generated complete plugin views with shared runtime mappings. Candidate B used a narrow terminal job boundary, leaving planning and judgment with the host. The chosen design combines A's immutable source and complete packaging with B's minimal deterministic process runner. Rejected alternatives were manual workflow rewrites, a hosted router daemon, and wholesale adoption of a community fork's policy changes.

## Ownership

`upstream/pstack` and `upstream.lock.json` own provenance. `tools/build.py` owns generated packaging. `adapters/` owns tool/host interpretation. `runtime/` owns external launch, lifecycle and evidence. Project configuration owns version binding and identity. The coordinating agent owns design, candidate comparison, verification and actual merge authority.

## Throughput checkpoint

- Blocking first steps: validate source inventory and runtime contracts before publication.
- Independent workstreams: runtime, package generation, and persistence tools have disjoint source directories.
- Shared mutable state: each job writes its own directory; one build owner writes generated output. No concurrent application writers.
- Smallest safe decomposition: three implementation owners and independent final review. Provider authentication and GitHub creation can proceed separately from code.

## Verification units

1. Pristine source and package baseline.
2. CLI process boundary and failure/recovery tests.
3. Persistent project bootstrap and fresh installation.
4. Full upstream helper tests where runtime dependencies permit.
5. Installed workflow execution and private plugin publication.
6. GitHub publication and any authenticated external-provider checks.

The build does not reduce unavailable original requirements to weaker success criteria.
