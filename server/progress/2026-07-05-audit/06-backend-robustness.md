# Backend robustness — atomic writes, schema-true protocol parsing, error mapping

**Context:** Zoo backend (`zoo/`), CubOS readable at `/Users/alexchan/Documents/Ursa/CubOS` (do not modify CubOS). Tests: `.venv/bin/python -m pytest tests/ -q`. Keep routers thin per CLAUDE.md. NOTE: items 1–2 change behavior that `tests/` may pin — update those tests deliberately.

## 1. Atomic, comment-preserving YAML writes (`zoo/services/yaml_io.py:27-29`)

`write_yaml` truncates in place (`"w"` + `yaml.dump`): a crash mid-dump corrupts the lab's config, a concurrent GET can read a truncated file, and every save strips the YAML comments that shipped configs rely on (see `configs/deck/asmi_deck.yaml`).

**Fix:** (a) switch `read_yaml`/`write_yaml` to `ruamel.yaml` round-trip mode (`YAML(typ="rt")`) so comments and key order survive load→save (add `ruamel.yaml` to `pyproject.toml` deps); (b) write via `NamedTemporaryFile(dir=path.parent, delete=False)` + `os.replace(tmp, path)` (atomic on POSIX and Windows). Apply the same atomic pattern to `raw.py`'s `path.write_text`. Verify: round-trip a commented YAML through PUT/GET and assert comments survive on disk.

## 2. Protocol GET/PUT must not silently drop data (`zoo/routers/protocol.py:112-117,126-138`)

GET skips any step that isn't a single-key dict (`continue`, no warning); the UI's load→save round trip then rewrites the file without those steps and without any unknown top-level keys — silent data destruction. This also duplicates parsing CubOS owns.

**Fix:** in `get_protocol`, replace the hand-rolled loop with CubOS `ProtocolYamlSchema.model_validate(data)` (see `/Users/alexchan/Documents/Ursa/CubOS/src/protocol_engine/loader.py:108-124`) and build steps from `schema.protocol`; map `ValidationError` → `HTTPException(400, str(e))` so malformed files are rejected, not silently rewritten. In `save_protocol`, read the existing file first and merge: preserve unknown top-level keys, overwrite only `protocol` and `positions`. Validate the merged doc through `ProtocolYamlSchema` before writing (400 on failure). Update any existing tests that pinned the silent-skip behavior.

## 3. `read_yaml` must reject non-mapping YAML (`zoo/services/yaml_io.py:18-24,32-40`)

`read_yaml` returns whatever `safe_load` produced; a scalar-string YAML containing the word "protocol" passes the `"protocol" not in data` substring check and then 500s on `data["protocol"]`. Same substring bug misclassifies configs in `classify_config`. **Fix:** after loading, `if not isinstance(data, dict): raise YamlConfigError(f"{path.name} is not a YAML mapping")`. Add a test: GET a scalar-YAML protocol file → 400 not 500.

## 4. `recover-limit` tells operators to E-stop over a validation error (`zoo/routers/gantry.py:469-474`)

`POST /calibration/recover-limit` with `{}` makes CubOS raise `ValueError("Limit recovery requires the failed jog delta.")`; Zoo's substring match (`"limit" in msg`) returns the 409 "Use E-stop/controller reset" message. **Fix:** catch `ValueError` first → 400 via `_session_http_exception`; restrict the 409 branch to `GantryAlarmError` or `looks_like_limit_alarm(str(exc))` (import from CubOS `gantry.limit_recovery`). Also in `_session_http_exception` (gantry.py:191), key the `"require"` check off exception type where possible. Test: recover-limit with `{}` → 400, not 409.

## 5. Data routes 500 on corrupt/non-SQLite DB (`zoo/routers/data.py:44-47,54-60,72-75`)

Only `DataExportError` is caught; a non-SQLite file at `data_db_path` propagates `sqlite3.DatabaseError` as a 500. **Fix:** add `except sqlite3.DatabaseError as exc: raise HTTPException(400, f"Data database is unreadable: {exc}")` to the three data routes. Test with a text file at the DB path.

## 6. Raw router: subdirectory layout + live-session refresh (`zoo/routers/raw.py:17,25`)

Raw GET/PUT use `configs_dir / filename` flat while every other router prefers `configs_dir/<kind>/` via `resolve_config_path` — files listed by `/api/deck/configs` 404 in the raw editor and raw PUTs write flat shadow copies. Also `put_raw` never calls `session.refresh_connected_config`, so raw-editing the connected gantry YAML leaves the live jog guard on stale working_volume. **Fix:** route raw reads/writes through `resolve_config_path` (probe kind subdirs); after a successful raw PUT that parses as a valid `GantryYamlSchema`, call `refresh_connected_config` like `put_gantry` (gantry.py:582-584) does. Reject content that fails `yaml.safe_load` with 400.

## 7. Settings: persistence + browse robustness (`zoo/routers/settings.py:31-65`, `zoo/config.py`)

- `PUT /api/settings` mutates the in-memory singleton only — silently reverts on restart. **Fix:** persist `config_dir` to `~/.zoo/settings.json` on update; load it in `ZooSettings` construction (env var still wins).
- `POST /settings/browse` non-darwin branch runs `tkinter.Tk()` on a worker thread — crash-prone, blocks forever, 500s headless. **Fix:** run the dialog via `subprocess` one-liner with `timeout=120` (mirroring the osascript branch) and wrap failures into `HTTPException(400, ...)`.

## 8. `python -m zoo` crashes on Windows without prebuilt dist (`zoo/__main__.py:23-27`)

`subprocess.run(["npm", ...])` → `FileNotFoundError` on Windows (npm is `npm.cmd`). **Fix:** resolve via `shutil.which("npm")`; if not found, log a clear warning ("npm not found — frontend will not be served") instead of crashing.

## 9. Boundary cleanups

- `zoo/routers/data.py:19-20,109-117`: `_format_cell`/`_json_array` wrappers are dead production code importing private CubOS APIs (used only by two tests). Delete the wrappers and those two tests.
- `zoo/routers/deck.py:166-173`: `_LABWARE_TYPE_MAP` hardcodes CubOS's class→type mapping and already misses `Wall`. Derive `type` from the raw YAML entry (the config dict Zoo just read — it contains `type` after load_name expansion) instead of inferring from CubOS class names.

**Done when:** all items implemented, full backend suite green, and frontend tests still pass (`cd frontend && npm run test`).
