# Fabricated unit fixture

All files here are fabricated parser inputs. They contain no provider execution proof. `unit-smoke.json` declares `evidenceKind` `unit-fixture`; default validation rejects it. `--allow-unit-fixtures` returns `fixture-only` without selecting a model or establishing availability. Tests may exercise algorithm branches with in-memory simulations. Those are never real captured evidence.

Real captured receipts and artifacts remain in private `.pstack/runs` or `.pstack-checks` directories. Build a captured bundle using the strict adapter contract and independently observed artifact checks. Do not copy private prompts/events or credentials into this directory.
