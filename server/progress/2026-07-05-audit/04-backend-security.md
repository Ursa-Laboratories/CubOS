# Backend security — origin checking + path traversal

**Context:** Zoo (FastAPI, `zoo/`) binds 127.0.0.1:8742 with no auth. Findings confirmed against code. Tests: `.venv/bin/python -m pytest tests/ -q`. Keep routers thin per CLAUDE.md.

## 1. MAJOR — motion endpoints are CSRF-triggerable (`zoo/app.py:30-42`)

`POST /api/gantry/home`, `/unlock`, `/reset-unlock`, `/feed-hold`, `/jog-cancel`, `/disconnect`, and `/connect` (body optional) take no request body → CSRF-simple requests. Any web page open while Zoo runs can `fetch("http://127.0.0.1:8742/api/gantry/connect", {method:"POST", mode:"no-cors"})` then `/home` and physically move the gantry. `ZOO_HOST=0.0.0.0` escalates to LAN-wide control.

**Fix:** add middleware in `create_app()` that, for state-changing methods (POST/PUT/DELETE):
- Rejects with 403 when an `Origin` (or, absent that, `Referer`) header is present and its host:port doesn't match the server's own (`http://{settings.host}:{settings.port}`, and accept `localhost` ↔ `127.0.0.1` equivalents).
- Rejects `Host` headers other than the configured host:port / localhost equivalents (blocks DNS rebinding) — apply this check to GET too.
Same-origin requests from the served frontend have a matching Origin and are unaffected; requests with no Origin/Referer (curl, tests) pass. Add tests: cross-origin POST to `/api/gantry/home` → 403; same-origin POST → passes through; no-Origin POST → passes; evil `Host` header → 403 (or 400).

## 2. MAJOR — path traversal via `{filename}` path params (Windows)

`zoo/routers/raw.py:17,25` and `zoo/services/yaml_io.py:43-48` (used by deck.py:57,115, gantry.py:562,575, protocol.py:101,128) build `configs_dir / filename` unsanitized. On Windows, URL-encoded backslashes pass route matching: `PUT /api/raw/..%5C..%5C..%5Cx.bat` writes an arbitrary file (pathlib treats `\` and `C:\...` as separators/anchors). Zoo ships a Windows installer, so this is real.

**Fix:** add `safe_filename(filename: str) -> str` in `zoo/services/yaml_io.py` that raises `ValueError` unless `Path(filename).name == filename`, `filename not in ("", ".", "..")`, and neither `/` nor `\\` appears in it. Call it inside `resolve_config_path()` and in both `raw.py` handlers. Map `ValueError` to HTTP 400 in the routers. Tests: `%5C`-encoded traversal on raw PUT → 400/404; plain names still work.

## 3. MAJOR — path traversal via JSON body file names (all OSes)

`zoo/routers/gantry.py:534-546` (`ConnectRequest.filename`) and `zoo/routers/protocol.py:163-187,219-251` (`gantry_file`/`deck_file`/`protocol_file`): body strings aren't routing-constrained, so `{"gantry_file": "../../../../etc/passwd"}` reaches CubOS loaders. Pydantic `ValidationError` messages include `input_value=...`, so `/api/gantry/connect` and `/api/protocol/validate-setup` responses leak arbitrary file contents.

**Fix:** apply `safe_filename()` (item 2) to `ConnectRequest.filename`, `RunProtocolRequest.*`, and `ProtocolSetupValidationRequest.*` before `resolve_config_path`, returning 400 on violation. Tests: traversal in each body field → 400 with no file contents in the response.

**Done when:** all three fixes implemented with the listed tests, existing 95 backend tests pass, and the frontend still works against same-origin requests (frontend tests pass).
