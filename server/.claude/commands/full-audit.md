---
description: Full production audit of Zoo — find issues, write prompt files, implement with subagents, verify, open a PR
---

Run a full production-readiness audit of the Zoo repo, then implement every finding. The goal is complete ONLY when all findings are implemented and verified. This mirrors the audit completed 2026-07-05 (see `progress/2026-07-05-audit/00-INDEX.md` for the format and that run's deferred items — do not re-report items listed there as deliberately deferred unless circumstances changed).

## Phase 0 — Baseline
- Ensure a clean `git status` on the default branch; create branch `audit/auto-YYYY-MM-DD`.
- Verify the environment: `.venv/bin/python -m pytest tests/ -q` and `cd frontend && npm run test && npm run lint && npm run build` must be green BEFORE auditing. If CubOS imports fail, reinstall editable from the sibling CubOS repo. If baseline is red, fix the environment or report and stop — never audit on a broken baseline.

## Phase 1 — Audit (parallel read-only subagents)
Fan out audit agents over: (1) changes since the last audit (`git log` since the newest `progress/*-audit/` directory date — focus effort where code changed); (2) backend routers/services vs the CubOS boundary rules in CLAUDE.md/AGENTS.md; (3) gantry control + calibration UX flows; (4) deck/protocol/results/settings UX flows; (5) test coverage + test quality (run coverage both sides); (6) the Windows installer if it changed. Agents must confirm findings in code — no speculation.

## Phase 2 — Prompt files
Write findings as self-contained task prompt files in `progress/YYYY-MM-DD-audit/` (kebab-case, numbered, one concern each, concrete file:line references, explicit "Done when" criteria), plus `00-INDEX.md` with an execution-order table that keeps tasks sharing files out of the same parallel wave. Reconcile conflicts between files before executing.

## Phase 3 — Implement
Execute each prompt file with an implementation subagent, sequenced per the INDEX waves (backend track / frontend track; test-gap tasks last so tests pin final behavior). Each agent: read CLAUDE.md + AGENTS.md first, stay in its file scope, never modify CubOS, never commit. Verify each task's "Done when" before marking it done in the INDEX.

## Phase 4 — Verify & ship
- Full verification: backend pytest, frontend test + lint + `tsc -b`/build. Fix anything red.
- Commit to the audit branch (include the audit prompt files), push, and open a PR titled "Automated audit YYYY-MM-DD: <one-line scope>" summarizing findings by severity, with test-count/coverage deltas and anything deliberately deferred. Watch CI checks and fix failures.
- If the audit finds NOTHING actionable, do not open a PR — just report that the audit came back clean.

## Guardrails
- Never touch hardware-facing runtime behavior without a test pinning it.
- Never push to `main` directly; PR only.
- configs/, .coverage, frontend/coverage/ stay uncommitted.
- Respect the deferred list in the most recent audit INDEX.
