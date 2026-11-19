"""Serve the built Operator and local, read-only API fixtures."""
import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from fixtures import GANTRY, SETUPS, sample_deck


HERE = Path(__file__).resolve().parent
CONFIG_DIR = "Read-only instrument preview"
DEFAULT_SETUP = "pipettes"
PROTOCOL = "preview.yaml"
DECK = sample_deck()
CONFIGS = {f"{slug}.yaml": {**GANTRY, "instruments": instruments}
           for slug, (_, instruments) in SETUPS.items()}
INSTRUMENT_TYPES = {}
PIPETTE_MODELS = {}
for config in CONFIGS.values():
    for instrument in config["instruments"].values():
        kind, vendor = instrument["type"], instrument["vendor"]
        INSTRUMENT_TYPES.setdefault(kind, set()).add(vendor)
        if model := instrument.get("pipette_model"):
            PIPETTE_MODELS[model] = vendor

RESPONSES = {
    "/settings": {"config_dir": CONFIG_DIR},
    "/system/update": {"update_available": False, "current_sha": "local-preview"},
    "/health": {"status": "preview"},
    "/gantry/configs": list(CONFIGS),
    **{f"/gantry/{filename}": {"filename": filename, "config": config}
       for filename, config in CONFIGS.items()},
    "/gantry/position": {"x": 0, "y": 0, "z": 0, "work_x": None, "work_y": None, "work_z": None,
                         "status": "Not connected", "connected": False, "calibration_active": False},
    "/gantry/instrument-types": [{"type": kind, "vendors": sorted(vendors), "is_mock": False}
                                 for kind, vendors in sorted(INSTRUMENT_TYPES.items())],
    "/gantry/pipette-models": [{"key": model, "name": model, "vendor": vendor}
                               for model, vendor in PIPETTE_MODELS.items()],
    "/gantry/instrument-schemas": {},
    "/gantry/instrument-methods": {},
    "/gantry/instrument-method-params": {},
    "/deck/configs": [DECK["filename"]],
    f"/deck/{DECK['filename']}": DECK,
    "/protocol/configs": [PROTOCOL],
    f"/protocol/{PROTOCOL}": {"filename": PROTOCOL, "positions": {}, "steps": []},
    "/protocol/commands": [],
    "/protocol/run-status": {"active": False, "protocol_file": None},
    "/data/campaigns": [],
    "/fluid-states": [],
    "/runs": [],
}


class Preview(BaseHTTPRequestHandler):
    def __init__(self, *args, dist, **kwargs):
        self.dist = dist
        super().__init__(*args, **kwargs)

    def reply(self, status, content, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if status != 200 or not self.path.startswith("/assets/")
                         else "public, max-age=31536000, immutable")
        if status == 405:
            self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                         "connect-src 'self'; object-src 'none'")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def json_reply(self, status, payload):
        self.reply(status, json.dumps(payload).encode(), "application/json")

    def index(self, query):
        slug = query.get("setup", [DEFAULT_SETUP])[0]
        if slug not in SETUPS:
            slug = DEFAULT_SETUP
        fixture = {"configDir": CONFIG_DIR, "gantry": f"{slug}.yaml",
                   "deck": DECK["filename"], "protocol": PROTOCOL, "active": slug,
                   "setups": {key: title for key, (title, _) in SETUPS.items()}}
        payload = json.dumps(fixture).replace("<", "\\u003c")
        preview_markup = (
            f'<script id="preview-fixture" type="application/json">{payload}</script>'
            '<script src="/preview/bootstrap.js"></script>'
            '<link rel="stylesheet" href="/preview/preview.css">'
        )
        content = (self.dist / "index.html").read_text().replace(
            "<head>", "<head>" + preview_markup, 1
        )
        self.reply(200, content.encode(), "text/html; charset=utf-8")

    def do_GET(self):
        request = urlsplit(self.path)
        path = unquote(request.path)
        if path.startswith("/api/v1/"):
            payload = RESPONSES.get(path[len("/api/v1"):])
            if payload is None:
                return self.json_reply(404, {"detail": "Endpoint unavailable in this read-only preview."})
            return self.json_reply(200, payload)
        if path == "/":
            return self.index(parse_qs(request.query))
        if path in ("/preview/bootstrap.js", "/preview/preview.css"):
            file = HERE / Path(path).name
        else:
            file = (self.dist / path.lstrip("/")).resolve()
            if not file.is_relative_to(self.dist) or not file.is_file():
                return self.json_reply(404, {"detail": "Not found."})
        self.reply(200, file.read_bytes(), mimetypes.guess_type(file)[0] or "application/octet-stream")

    do_HEAD = do_GET

    def reject_write(self):
        self.json_reply(405, {"detail": "The local preview serves read-only fixtures."})

    do_POST = do_PUT = do_PATCH = do_DELETE = reject_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=5197, type=int)
    parser.add_argument("--dist", default=HERE.parent.parent / "dist", type=Path)
    args = parser.parse_args()
    dist = args.dist.resolve()
    if not (dist / "index.html").is_file():
        parser.error(f"Build Operator before starting the preview. Missing {dist / 'index.html'}")
    handler = partial(Preview, dist=dist)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
