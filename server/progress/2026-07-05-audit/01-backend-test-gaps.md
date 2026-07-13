# Backend test gaps — close untested risky paths

**Context:** Zoo backend (FastAPI over CubOS) is at 87% coverage with 95 passing tests, but the uncovered 13% includes hardware-touching error paths and one whole endpoint. Run tests with `.venv/bin/python -m pytest tests/ -q`. Follow existing test styles in `tests/` (real ASGI requests, recorder-style `FakeSession`, real seeded sqlite DBs).

**Goal:** add the following backend tests. Do not change production code except where explicitly noted.

## 1. `POST /api/deck/preview-wells` — zero tests today (biggest gap)

In `tests/test_deck_router.py`, add three tests (no mocks — real CubOS logic):
- POST a valid well-plate entry (reuse the calibration shape from `test_get_deck_normalizes_current_well_plate_editor_fields`: `calibration: {a1: {x:347,y:42,z:30}, a2: {x:338,y:42,z:30}}, x_offset: 9, y_offset: 9`, default rows/columns) → assert 200 and exact coords for `A1` plus one derived well (round to 3dp).
- Same body with `z` omitted from `a1` → assert 400 and `"Calibration A1 must include z"` in detail.
- Garbage body `{"calibration": "nope"}` → assert 400.

## 2. Parametrized error-path sweep over hardware endpoints (`zoo/routers/gantry.py`)

In `tests/test_gantry_router.py`, add a `@pytest.mark.parametrize` sweep over:
`[("POST","/api/gantry/feed-hold","feed_hold"), ("POST","/api/gantry/jog-cancel","jog_cancel"), ("POST","/api/gantry/unlock","unlock"), ("POST","/api/gantry/reset-unlock","reset_and_unlock"), ("POST","/api/gantry/calibration/prepare-origin","prepare_calibration_origin"), ("POST","/api/gantry/calibration/home-and-center","calibration_home_and_center"), ("POST","/api/gantry/calibration/restore-soft-limits","restore_calibration_soft_limits"), ("GET","/api/gantry/grbl-settings","read_grbl_settings"), ("POST","/api/gantry/jog","jog")]`

For each: monkeypatch the named method on `FakeSession` to raise `GantryAlarmError("alarm")` → assert 409; and `GantrySessionError("boom")` → assert 500.

Plus: `finalize-origin` raising `CalibrationBlockedError` → 400. And `recover-limit` raising `RuntimeError("serial died")` (message contains neither "alarm" nor "limit") → assert **500** with `"Limit recovery failed"` — this pins `gantry.py:475`, the branch deciding whether the operator sees the e-stop 409 message.

## 3. New `tests/test_app_lifespan.py` — gantry disconnect on shutdown

No HTTP needed: `async with zoo.app.lifespan(create_app()): pass` with `zoo.routers.gantry._session` set to a fake with `connected=True` and a recording `disconnect()`. Assert `disconnect` called and `gantry_router._session is None` after. Second test: `disconnect` raises `RuntimeError` → no exception escapes, `_session` still reset. (Verified implementable exactly as written.)

## 4. Corrupt-schema campaign DB → clean 400

In `tests/test_data_router.py`: create a sqlite file containing only `CREATE TABLE campaigns (id INTEGER PRIMARY KEY)`, monkeypatch `get_settings().data_db_path` to it, `GET /api/data/campaigns` → assert 400 with detail `"Data database is missing table(s): experiments"` (verified live). Pins that a corrupt DB yields a clean 400, not a 500 traceback (`zoo/routers/data.py:46-47`).

## 5. New `tests/test_raw_router.py`

With `config_dir` monkeypatched to a tmp dir:
- `GET /api/raw/missing.yaml` → 404 `"Config not found"`.
- `PUT /api/raw/notes.yaml` with `{"content": "a: 1\n"}` → 200 echoing content; subsequent `GET` returns identical content and file exists on disk.
- `GET /api/raw/..%2Fescape.yaml` → assert 404 (pins Starlette's traversal rejection so a future route change to `{filename:path}` fails loudly).

## 6. Protocol malformed-file handling

NOTE: prompt file `06-backend-robustness.md` item 2 changes GET to reject malformed protocols via CubOS `ProtocolYamlSchema` instead of silently skipping steps. Write tests against the FINAL behavior: a protocol YAML whose `protocol` list contains a valid step plus a bare string `"oops"` (or a two-key dict) → `GET` returns **400** with a validation message, and a valid file round-trips GET→PUT preserving unknown top-level keys. If 06 has not been implemented yet, implement these tests after it.

**Done when:** all new tests pass, existing 95 tests still pass, and `pytest --cov=zoo` shows `deck.py` ≥ 95%, `gantry.py` ≥ 97%, `raw.py` 100%, `app.py` ≥ 95%.
