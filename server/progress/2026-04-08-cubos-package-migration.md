# CubOS package migration

Status: complete

## Goal
- Install CubOS from its Git repository instead of a local checkout.
- Remove local-source import hacks so Zoo imports CubOS from the installed package.
- Store YAML configs in a Zoo-local directory instead of a CubOS source path.

## Findings
- Zoo now installs CubOS from `git+https://github.com/Ursa-Laboratories/CubOS.git@main`.
- `zoo/cubos.py` and the startup `sys.path` mutation were removed so Zoo relies on the installed package modules.
- Zoo settings now expose a local `config_dir` instead of a browsed CubOS source path.
- Follow-up request completed: the UI now exposes a browse button so the local config directory can be selected without typing.
- Removed the stale editable self-install of Zoo from `requirements.txt`; it was the reason `src/zoo/` appeared as a nested checkout.
- Deleted the generated `src/` directory from the working tree.
- Moved CubOS compatibility initialization into `create_app()` so router package imports are side-effect free.
- Upstream CubOS now packages `instruments/registry.yaml`; the temporary Zoo fallback was removed.

## Files
- `requirements.txt`
- `pyproject.toml`
- `.gitignore`
- `zoo/config.py`
- `zoo/app.py`
- `zoo/routers/__init__.py`
- `zoo/routers/settings.py`
- `tests/test_settings_router.py`
- `tests/test_protocol_router.py`
- `tests/test_board_router.py`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`

## Verification
- `pytest tests`
- `pytest tests/test_settings_router.py`
- `pytest tests/test_settings_router.py tests/test_protocol_router.py tests/test_board_router.py`
- `npm test -- --run src/App.test.tsx`
- `npm run build`
- Verified installed module origins resolve from `site-packages` for `deck`, `board`, `gantry`, `protocol_engine`, `instruments`, and `validation`.
- Verified `/Users/alexchan/.pyenv/versions/3.13.1/lib/python3.13/site-packages/instruments/registry.yaml` exists after reinstalling CubOS from `main`.

## Next Steps
- None for this migration.
