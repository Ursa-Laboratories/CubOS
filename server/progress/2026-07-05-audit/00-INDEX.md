# Zoo production-readiness audit — 2026-07-05

Full audit of Zoo (UI/UX flows, backend robustness, test coverage, Windows installer fix on branch `codex/fix-windows-installer-runtime`). Each numbered file is a self-contained task prompt suitable for a `/goal` run. Baseline before changes: 95 backend tests, 112 frontend tests, all green; backend coverage 87%, frontend 81.5%.

## Execution order (files sharing code must not run concurrently)

| Wave | Files | Why grouped |
| --- | --- | --- |
| 1 | 03 (installer), 04 (backend security), 09 (editor data loss) | Disjoint: installer/, zoo/ security surface, frontend editors |
| 2 | 05 (session safety), 07 (calibration safety), 11 (deck viz/results/settings) | 05 after 04 (both touch routers); 07 touches wizard + tiny gantry.py model add; 11 touches DataOutputPanel/client.ts |
| 3 | 06 (backend robustness), 08 (gantry widget UX), 10 (protocol run flow) | 06 after 04+05 (yaml_io/routers overlap); 08 after 07 (widget overlap); 10 after 05 (run-status) + 09 (App.tsx overlap) |
| 4 | 01 (backend test gaps), 02 (frontend test gaps) | Last — tests must pin FINAL behavior after all fixes |

## Status

| File | Scope | Status |
| --- | --- | --- |
| 01-backend-test-gaps.md | preview-wells, gantry error sweep, lifespan, raw router, corrupt DB, protocol 400 | ✅ done (191 passed, 95% cov) |
| 02-frontend-test-gaps.md | GantryPositionWidget, run failures, payload assertions, client.ts | ✅ done (174 FE tests, 88.9% stmts; GantryEditor stale-field drop implemented as follow-up) |
| 03-windows-installer-fixes.md | ASMI default-selection bug (critical), repair flow, diagnostics, EAP traps | ✅ done (3 passed, 1 skipped-no-pwsh) |
| 04-backend-security.md | Origin/Host middleware, path traversal (path + body params) | ✅ done (119 passed) |
| 05-backend-session-safety.md | connect-while-connected 409, run gate + run-status endpoint, session lock | ✅ done (129 passed) |
| 06-backend-robustness.md | atomic+comment-preserving YAML, protocol schema parsing, error mapping, settings persistence | ✅ done (142 passed) |
| 07-calibration-safety.md | refresh mid-calibration, retry frame corruption, save-as reconnect, stale-delta recovery | ✅ done (149 FE / 144 BE) |
| 08-gantry-widget-ux.md | keyboard jog scoping, run lockout, error surfacing, jog-cancel, focus trap | ✅ done (145 FE tests) |
| 09-editor-data-loss.md | dirty-switch confirm, beforeunload, save errors, discard, key collision | ✅ done (127 FE tests) |
| 10-protocol-run-flow.md | cancel semantics, global run banner, validate gating, method-map endpoint | ✅ done (139 FE / 143 BE) |
| 11-deck-viz-results-settings.md | well preview, ASMI export button, empty states, error formatting, mm/px scale | ✅ done (133 FE tests) |

## Deliberately deferred (not in scope of the prompt files)

- **Concurrent-edit mtime checks (last-write-wins between two tabs):** real but low-likelihood for a single-operator bench tool; would change every GET/PUT contract. Revisit if multi-station use appears.
- **CubOS-side public API exports** (`derive_wells_preview`, labware type mapping, measurement-method reflection source): Zoo-side mitigations are in 06/10; the clean fix needs CubOS changes on the pinned branch — coordinate separately.
- **Auth tokens for the local API:** Origin/Host middleware (04) covers the browser attack surface; full token auth deferred until remote access is a requirement.

## Environment note

Zoo's `.venv` had CubOS installed editable from a stale path (`~/Documents/hephaestus/CubOS`); fixed 2026-07-05 by `pip install -e /Users/alexchan/Documents/Ursa/CubOS` (local `new-docs` branch, a superset of the pinned `codex/python-protocol-builder`).
