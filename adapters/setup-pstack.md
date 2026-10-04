# Portable setup-pstack

This adapter translates the original seven setup steps to portable configuration. Read the [contract](CONTRACT.md), matching host adapter and current project pin first. Preserve all 17 upstream role labels, inherited aliases and configured panel counts. The layered preferences in [routing-layers.json](../config/routing-layers.json) are a proposal. They are not benchmark winners or applied configuration.

The setup data shape is a short-lived plan with budget intent, layer preferences, requested tuples, effective tuples, capabilities, unmet requirements, task-sensitive alternatives, optional effort escalations and a digest. Deployed `roles` remain explicit provider/transport/model/effort objects. No runtime layer resolver is introduced.

## The original seven steps

1. Detect available models. Discover the actual native host spawn schema separately from external provider catalogs. Native transports only accept native schema entries. Capture available model identifiers, effort combinations and real capabilities in caller-owned JSON. Aliases `auto` and `inherit-parent` omit model and effort overrides. Neither requires a catalog entry. Never infer availability or file-tool support from a model name.
2. Load current state. Read portable project/user configuration instead of the Cursor rule. Preserve current family, effort, list and alias choices. A current role equal to the known prior GPT default is eligible for the proposed layered replacement. Show retired role labels that would be dropped. Keep unrelated configuration and the project pin unchanged.
3. Budget, map and confirm. Offer the four exact original labels below. Default layered planning retains the budget intent while recording explicit per-role effort overrides. Exploration requests standard Grok 4.7 low, routine work medium, complex work high, judgment Astra medium and explanation Astra low. Fast and xhigh are never layered defaults. High and xhigh remain optional task-evaluation-justified escalations wherever the actual model/effort schema and role capabilities support them; neither is prohibited. An explicit `--budget` creates the original uniform effort transformation, including panel entries, using the highest discovered effort at or below its target. If none exists, stop for a choice. Existing aliases stay unchanged. Show the entire confirmation table and saved discovery before asking the host's user whether to accept or change specific roles. Panel lengths remain 2/1/2/2. The cross-judge pool still supplies one choice, and the workflow selects a different family when possible.
4. Validate. Run the helper against the current configuration and actual catalog. Every requested real tuple must be discovered available with its effort. Capabilities must meet the role's requirements. Response-only Grok cannot read, edit or verify files. Such rows retain their Grok preference, show `needs-file-proof`, and propose an available native Sol 6.1 high effective file lane. If no supported effective lane exists, show `NEEDS CHOICE` and stop before exporting a candidate. This visible proposal requires confirmation. A provider failure stops the call; it never selects another provider silently.
5. Write the rule. Export a candidate only after reviewing the plan. Export does not imply approval or application. The helper never writes current configuration and never accepts a typed approval token. The host obtains explicit user confirmation for the complete table and exact plan digest, revalidates against unchanged current state and discovery, then writes the confirmed candidate to the portable project/user scope. Preserve the exact role labels, aliases and panel counts. Keep private discovery, prompts, receipts and plans under `.pstack/runs` or `.pstack-checks`; credentials stay outside Git.
6. Confirm. Only after the host write, state the destination, effective bindings, retained preferences, substitutions and when the host applies the configuration. Do not claim a dry run or candidate export changed new sessions.
7. Offer a verification skill. Reuse an existing project verifier. When none exists, offer the original optional project-local verification skill once. Provider comparison uses [verify-model-routing](../skills/verify-model-routing/SKILL.md) and the [selection policy](model-selection.md). Rank measured task-relevant options with repeated evidence and uncertainty. There is no universal single winner. Preserve the incumbent when evidence is inconclusive. File-lane promotion needs actual task-relevant file-tool proof and a separately confirmed setup table.

The four budget labels remain exact.

- `unlimited — keep max`
- `large — xhigh reasoning`
- `medium — high reasoning`
- `small — medium reasoning`

## Task-sensitive judgment and effort policy

Every Astra slot considers GPT-6.1 Sol/high before dispatch. This includes prose, judgment, hardest tasks, reflection, every panel Astra entry and the low-effort explainer. Prefer Sol/high for bounded routine judgment or prose when it meets the task's acceptance and capability requirements. Use Astra when task evaluation warrants its cost for the harder or more ambiguous work. This is an approved task-selection policy, not a claim that either model wins every task. Preserve panel entry counts, candidate independence, judging order and required capabilities when making the explicit choice. Two entries choosing Sol remain two independent instances and provide same-family review; this does not establish cross-family proof.

The plan carries `selection_policy.astra` and `selection_policy.effort_escalation`. Every Astra choice has an `alternatives` list containing the exact Sol/high tuple, discovered capabilities, missing requirements, availability and selection criteria. Unsupported Sol efforts, unavailable tuples or unmet capabilities leave the alternative explicitly unavailable. An alternative does not replace the table's requested or effective binding during planning or export. The coordinator records the task evaluation, selected tuple and reason before dispatch. A persistent role-table change still requires confirmation of its concrete table; a provider failure stops rather than selecting the alternative.

Each real choice also carries `optional_escalations` for higher high/xhigh efforts. These separate discovered effort support from satisfied capabilities and require a task evaluation, role capabilities and explicit selection. The plan does not turn optional escalations into defaults. Use repeated task-relevant evidence from the existing selection skill to decide when extra reasoning improves accepted outcomes; do not infer a prohibition or a winner from absence in the default table.

## Discovery input and CLI

The following shape illustrates fields, not observed availability. Populate every entry from actual host/provider discovery; do not use this example as proof. Native capabilities describe the host's supported tool lane. External file capabilities additionally require a nonempty `file_tool_proof` reference to task-relevant verified receipts. A response-only external entry can advertise `respond` only.

```json
{
  "schema_version": 1,
  "native_host": {
    "source": "saved actual spawn schema and host tool discovery",
    "models": [{"provider": "codex", "transport": "native", "model": "gpt-6.1-sol", "efforts": ["high"], "available": true, "capabilities": ["respond", "read_files", "edit_files", "verify"]}]
  },
  "external": {
    "source": "saved actual provider catalog and verified harness capabilities",
    "models": [{"provider": "grok", "transport": "grok-build", "model": "grok-4.7", "efforts": ["low", "medium", "high"], "available": true, "confinement": "response-only", "capabilities": ["respond"]}]
  }
}
```

Include the actual Astra entry and all user-chosen tuples before planning. Resolve the package root from the loaded skill. The Python standard-library helper reads local files only. It does not authenticate, call providers, probe tools, change pins or apply configuration.

```bash
python3 "$PSTACK_PACKAGE/runtime/setup_routing.py" plan --catalog "$PSTACK_CATALOG" --current "$PSTACK_CURRENT"
python3 "$PSTACK_PACKAGE/runtime/setup_routing.py" plan --catalog "$PSTACK_CATALOG" --current "$PSTACK_CURRENT" --plan-output "$PSTACK_PLAN" --output "$PSTACK_CANDIDATE"
python3 "$PSTACK_PACKAGE/runtime/setup_routing.py" validate --catalog "$PSTACK_CATALOG" --current "$PSTACK_CURRENT" --plan "$PSTACK_PLAN"
```

Set each variable to its authorized absolute path. Omitting output arguments performs zero writes. Output paths cannot overwrite any input or each other. `validate` rejects changed capabilities, plan edits, substitutions, budget labels, role labels, aliases, panel counts or current configuration. After validation the host still owns user confirmation and the approved write. Successful parser validation proves a consistent plan, not live provider operation or truthful catalog capture.

Persist only requested/effective bindings and shared selection policy. Keep full capability discovery and alternatives in the private setup plan, then regenerate them from current discovery. This reduces repeated context and avoids treating historical availability as current readiness.
