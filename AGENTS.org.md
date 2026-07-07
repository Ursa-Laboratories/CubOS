---
last_updated: 2026-07-07
owner: Alex Chan
scope: org-wide
---
# Ursa Labs — org agent guide
Synced into every repo. The repo's own AGENTS.md takes precedence over this file.

## What / why
- **CUB** — the lab-automation hardware itself (gantry + stations); printed parts live in `Cubware`.
- **CubOS** — the software layer that runs experiments and movement; all runtime behavior lives here.
- **Zoo** — the UI for CubOS; thin by design.
- **DEN** (`denos`) — deprecated; the live workcell workflow is `manual_bioadhesives_workcell`.
- Deprecated code lives in `archive/` at the workspace root — never build on anything inside it.

## Instrument & hardware access
| Task | Path |
|---|---|
| Any instrument, protocol, or movement control | Through CubOS (`CubOS/src/instruments/`, protocol engine) |
| Gantry movement via ASMI | Direct instrument access allowed — the only exception |

## Never / instead — each of these has needed repeated correction
- Never change experiment/movement behavior in Zoo — change it in CubOS and consume it from Zoo.
- Never cache or mirror CubOS state in a dependent repo — read it from CubOS at use time.
- Never reach a sibling repo via `sys.path`/PYTHONPATH hacks — depend on the installed `cubos` package.
- Never write docs only agents can parse — write for an everyday lab user: runnable commands, plain terms.

## Hardware safety
- Never execute motion or protocol runs on real hardware yourself — validate offline, then hand the operator an exact test procedure.
- Enforcement is PR review, not a hook: a PR touching motion, calibration, or hardware command sequences must state its hardware-validation status so the reviewer can check it.

## Environments & commands
- Use the repo's own venv; never install across repos or into system Python.
- Org-wide minimum is Python 3.9; a repo's own `requires-python` wins when higher (Zoo is >=3.11).
- Python repos: `pip install -e ".[dev]"`, then `python -m pytest -q`. Zoo frontend: `cd frontend && npm ci && npm run lint && npm run test`.
- No Python linter is configured in any repo — do not add or assume one.
- Zoo dev note: `.venv` deliberately holds an editable install of the local `CubOS/` checkout; pyproject pins `cubos @ git+...@main` for fresh installs.

## Read when
- Editing 2+ repos in one task (e.g. Zoo + CubOS together): read `Ursa_Context/AGENTS.md` first.
- Touching CubOS motion, deck, or calibration: read `CubOS/AGENTS.md` and `CubOS/docs/agent-index.md` first.
- Adding or updating printed parts: read `Cubware/AGENTS.md` first.
