# Zoo — CubOS Frontend

Zoo is a web UI (FastAPI + React) for configuring and controlling CubOS. It is **not** a standalone system — it is a thin frontend layer over CubOS.

## Architecture Rules

- **Never break CubOS abstractions.** Zoo must use CubOS's public classes and methods (e.g. `Gantry`, `Gantry.move_to`, `Gantry.get_coordinates`, `load_deck_from_yaml`, `GantryYamlSchema`) — never send raw serial/GRBL commands, never reimplement driver logic, never bypass CubOS to talk to hardware directly.
- **Never recreate CubOS functionality.** If CubOS already provides it (YAML schema validation, well position calculation, movement, protocol execution, deck resolution, instrument control), use it. Don't duplicate or rewrite it in Zoo.
- **Zoo routers are thin.** They write YAML from user input, read it back via CubOS loaders/schemas, and return the results. Business logic and validation belong in CubOS, not in Zoo.
- **Zoo models are API response shapes only.** They describe what the REST API returns (e.g. `GantryPosition`, `DeckResponse`). They must not duplicate CubOS's Pydantic schemas or validation logic.
- **CubOS is installed from Git and imported as a package.** Zoo must rely on the installed `cubos` package modules (for example `deck`, `gantry`, `protocol_engine`) and must not prepend local source directories onto `sys.path`.
- **Zoo stores configs locally.** YAML configs live in the repo-local `configs/` directory by default and can be redirected with the settings UI; the active directory is exposed through the settings API as `config_dir`.

## How Config Tabs Work

Each config tab (Deck, Gantry) follows the same pattern:
1. **Frontend** collects user input via form fields
2. **PUT** sends the raw config dict as JSON → Zoo writes it as YAML to Zoo's local `configs/`
3. **GET** reads YAML from Zoo's local `configs/` → validates/loads via CubOS loaders → returns structured JSON
4. CubOS's loaders handle all validation and derived data (e.g. well position calculation)

## Project Structure

```
zoo/
  app.py              # FastAPI app factory
  config.py           # ZooSettings (pydantic-settings)
  models/             # API response shapes only (gantry, protocol)
  routers/            # Thin FastAPI routers (deck, gantry, protocol, raw)
  services/           # yaml_io helper
frontend/
  src/
    api/client.ts     # API client functions
    types/index.ts    # TypeScript types describing CubOS YAML shapes
    theme.ts          # Design tokens + shared style objects (colors, buttons, notices)
    hooks/            # TanStack Query hooks
    components/       # React components
```

## Frontend

- React + TypeScript + Vite
- TanStack Query for server state
- Inline styles (no CSS framework); pull colors/radii/shadows and shared button/input/notice styles from `src/theme.ts` — don't hardcode hex values in components. Hover/focus/disabled states live in `src/index.css`.
- `npm run build` from `frontend/` — output goes to `frontend/dist/`, served by FastAPI

## Commands

- **Frontend build:** `cd frontend && npm run build`
- **Run server:** `python -m zoo` (or `uvicorn zoo.app:create_app --factory`)
- **Backend tests:** `pytest tests/`

In **TDD Mode** (planning sessions, new features, CubOS interface changes): write tests alongside implementation and update docs as you go. In **Hardware Iteration Mode** (iterative UI/config changes under active lab testing): defer tests and docs to close-out, mark deferred work `# TODO(iter)`. See root `AGENTS.md` for full mode definitions.

Agent retrieval rule: before coding, read `AGENTS.md` and `docs/agent-index.md`, then retrieve the specific source/docs named there for the subsystem you are touching. Prefer repo-grounded reasoning over model memory for Zoo/CubOS boundaries, coordinate display, config validation, and hardware-touching routes.
