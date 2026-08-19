#!/usr/bin/env python
"""Scrappy bench UI for exercising the Sartorius Picus 2 driver by hand.

Every button calls the real ``SartoriusPicus2Pipette`` from ``cubos`` -- no
reimplementation -- and the log shows the actual JSON frames the driver puts
on the wire and the replies it gets back, so you can verify what a command
turns into rather than trusting it.

Three transports:

    simulated  (default) real driver code against an in-process pipette that
               speaks the reply grammar. Shows real TX/RX frames with no
               hardware attached -- the useful default for checking that a
               command is constructed the way you expect.
    hardware   real pyserial against --port.
    offline    the driver's own ``offline=True`` path. No wire at all, so the
               log shows calls and return values only.

Usage:
    python tools/picus_bench.py                        # simulated, :8770
    python tools/picus_bench.py --transport hardware --port /dev/ttyACM0
    python tools/picus_bench.py --model picus2_1ch_10

Not part of the shipped package: a bench utility that lives beside the driver.
"""

from __future__ import annotations

import argparse
import itertools
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial as pyserial

from cubos.instruments.pipette.models import PICUS2_MODELS
from cubos.instruments.pipette.vendors import sartorius as sartorius_module
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette


# ── Wire plumbing ────────────────────────────────────────────────────────────


class _FakePicus:
    """In-process stand-in that speaks the Picus reply grammar.

    Deliberately permissive: it answers OK to anything it does not recognize,
    so the point of the simulated transport is checking what the driver
    *sends*, not simulating pipette behaviour.
    """

    def __init__(self, nominal_volume: float) -> None:
        self.is_open = True
        self._replies: list[bytes] = []
        self._scripted = {
            "GET_NOMINAL_VOLUME": [f"{nominal_volume:g}"],
            "GET_BATTERY_LEVEL": ["87"],
            "GET_MODEL": ["Picus 2 (simulated)"],
            "GET_SERIAL": ["SIM-0000"],
            "GET_VERSION": ["sim-1.0"],
        }

    def write(self, frame: bytes) -> None:
        payload = json.loads(frame.decode().strip())
        if "button" in payload:
            return  # softkey confirmations are acknowledged by the ENABLE reply
        data = payload["data"]
        for prefix, lines in self._scripted.items():
            if data.startswith(prefix):
                for line in lines:
                    self._replies.append(f"{line}\r\n".encode())
                break
        self._replies.append(b"ACK\r\n")
        self._replies.append(f"OK {payload['no']}\r\n".encode())

    def readline(self) -> bytes:
        return self._replies.pop(0) if self._replies else b""

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    def reset_input_buffer(self) -> None:
        pass


class _TeeSerial:
    """Wraps a serial object and copies every frame into the bench log."""

    def __init__(self, inner, log) -> None:
        self._inner = inner
        self._log = log

    def write(self, frame: bytes):
        self._log("tx", frame.decode("ascii", errors="replace").strip())
        return self._inner.write(frame)

    def readline(self) -> bytes:
        raw = self._inner.readline()
        if raw:
            self._log("rx", raw.decode("ascii", errors="replace").strip())
        return raw

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _SerialShim:
    """Stands in for the ``serial`` module inside the driver only.

    Patching ``sartorius_module.serial.Serial`` directly would mutate pyserial
    process-wide; replacing the module reference keeps the swap scoped to this
    one driver.
    """

    def __init__(self, factory) -> None:
        self.Serial = factory

    def __getattr__(self, name):
        return getattr(pyserial, name)


# ── Bench state ──────────────────────────────────────────────────────────────


class Bench:
    def __init__(self, model: str, transport: str, port: str) -> None:
        self.model = model
        self.transport = transport
        self.port = port
        self.pipette: SartoriusPicus2Pipette | None = None
        self.connected = False
        self._log: list[dict] = []
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._install_transport()

    # -- logging ------------------------------------------------------------

    def log(self, kind: str, text: str) -> None:
        self._log.append({"seq": next(self._seq), "kind": kind, "text": text})

    def entries(self, after: int) -> list[dict]:
        return [entry for entry in self._log if entry["seq"] > after]

    def _install_transport(self) -> None:
        nominal = PICUS2_MODELS[self.model].max_volume

        def factory(**kwargs):
            if self.transport == "hardware":
                inner = pyserial.Serial(**kwargs)
            else:
                inner = _FakePicus(nominal)
            return _TeeSerial(inner, self.log)

        sartorius_module.serial = _SerialShim(factory)

    # -- dispatch -----------------------------------------------------------

    def call(self, method: str, kwargs: dict) -> dict:
        with self._lock:
            if method == "construct":
                return self._construct()
            if self.pipette is None:
                self._construct()
            # Connect on demand. `connect()` is a required lifecycle step, so
            # without this the first thing you click fails with "Not connected
            # to pipette" -- and get_status confusingly succeeds, because the
            # driver catches a failed battery read by design.
            if method not in ("connect", "disconnect") and not self.connected:
                self.log("call", "connect()  [auto]")
                try:
                    self.pipette.connect()
                except Exception as exc:
                    self.log("err", f"{type(exc).__name__}: {exc}")
                    return {"ok": False, "error": f"auto-connect failed: {exc}"}
                self.connected = True
                self.log("ret", "None")
            target = getattr(self.pipette, method, None)
            if target is None or not callable(target):
                return {"ok": False, "error": f"no such method: {method}"}
            rendered = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            self.log("call", f"{method}({rendered})")
            try:
                result = target(**kwargs)
            except Exception as exc:
                self.log("err", f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if method == "connect":
                self.connected = True
            elif method == "disconnect":
                self.connected = False
            self.log("ret", repr(result) if result is not None else "None")
            return {"ok": True, "result": repr(result)}

    def _construct(self) -> dict:
        self.pipette = SartoriusPicus2Pipette(
            pipette_model=self.model,
            port=self.port,
            offline=self.transport == "offline",
        )
        self.log(
            "call",
            f"SartoriusPicus2Pipette(pipette_model={self.model!r}, "
            f"port={self.port!r}, offline={self.transport == 'offline'})",
        )
        return {"ok": True, "result": "constructed"}

    def reconfigure(self, model: str, transport: str, port: str) -> dict:
        with self._lock:
            if self.pipette is not None:
                try:
                    self.pipette.disconnect()
                except Exception:
                    pass
            self.model, self.transport, self.port = model, transport, port
            self.pipette = None
            self.connected = False
            self._install_transport()
            self.log("call", f"-- transport={transport} model={model} port={port or '-'} --")
            return {"ok": True, "result": "reconfigured"}


# ── HTTP ─────────────────────────────────────────────────────────────────────

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Picus 2 bench</title>
<style>
 body{font:13px ui-monospace,Menlo,monospace;margin:0;background:#14171a;color:#e6e6e6}
 header{padding:10px 14px;border-bottom:1px solid #2c3238;display:flex;gap:10px;
        align-items:center;flex-wrap:wrap}
 main{display:grid;grid-template-columns:340px 1fr;height:calc(100vh - 47px)}
 #cmds{padding:12px;overflow:auto;border-right:1px solid #2c3238}
 #log{padding:12px;overflow:auto;white-space:pre-wrap;line-height:1.55}
 fieldset{border:1px solid #2c3238;margin:0 0 12px;padding:8px 10px}
 legend{color:#8a949e;padding:0 4px}
 button{font:12px ui-monospace,monospace;background:#232a31;color:#e6e6e6;
        border:1px solid #3a434c;border-radius:4px;padding:5px 9px;cursor:pointer;margin:2px}
 button:hover{background:#2c343c}
 input,select{font:12px ui-monospace,monospace;background:#1b2025;color:#e6e6e6;
        border:1px solid #3a434c;border-radius:4px;padding:4px 6px;width:88px}
 label{color:#8a949e;margin-right:8px}
 .call{color:#7fb2ff}.tx{color:#e2b341}.rx{color:#6fcf8d}.ret{color:#d6d6d6}.err{color:#ff7b72}
</style>
<header>
  <label>model <select id=model></select></label>
  <label>transport <select id=transport>
    <option value=simulated>simulated</option>
    <option value=hardware>hardware</option>
    <option value=offline>offline</option></select></label>
  <label>port <input id=port style="width:150px"></label>
  <span id=state style="margin-left:auto;padding:3px 9px;border:1px solid #3a434c;border-radius:999px">…</span>
  <button onclick="reconfigure()">apply</button>
  <button onclick="document.getElementById('log').textContent=''">clear log</button>
</header>
<main>
 <div id=cmds>
  <fieldset><legend>session</legend>
   <button onclick="call('connect')">connect</button>
   <button onclick="call('disconnect')">disconnect</button>
   <button onclick="call('health_check')">health_check</button>
   <button onclick="call('warm_up')">warm_up</button>
   <button onclick="call('get_status')">get_status</button>
  </fieldset>
  <fieldset><legend>piston</legend>
   <button onclick="call('home')">home</button>
   <button onclick="call('prime')">prime</button>
  </fieldset>
  <fieldset><legend>liquid</legend>
   <div><label>volume µL <input id=vol value=500></label></div>
   <div><label>speed 0-100 <input id=speed value=50></label></div>
   <div><label>mix reps <input id=reps value=3></label></div>
   <button onclick="call('aspirate',{volume_ul:num('vol'),speed:num('speed')})">aspirate</button>
   <button onclick="call('dispense',{volume_ul:num('vol'),speed:num('speed')})">dispense</button>
   <button onclick="call('blowout',{speed:num('speed')})">blowout</button>
   <button onclick="call('mix',{volume_ul:num('vol'),repetitions:num('reps'),speed:num('speed')})">mix</button>
  </fieldset>
  <fieldset><legend>tips</legend>
   <div><label>tip mm <input id=tip value=59.3></label></div>
   <button onclick="call('pick_up_tip')">pick_up_tip</button>
   <button onclick="call('drop_tip')">drop_tip</button>
   <button onclick="call('set_attached_tip_extension',{extension_mm:num('tip')})">set tip ext</button>
   <button onclick="call('clear_attached_tip_extension')">clear tip ext</button>
  </fieldset>
  <fieldset><legend>identity</legend>
   <button onclick="call('get_model')">get_model</button>
   <button onclick="call('get_serial_number')">get_serial</button>
   <button onclick="call('get_nominal_volume')">get_nominal_volume</button>
  </fieldset>
 </div>
 <div id=log></div>
</main>
<script>
let after=0;
const PREFIX={call:'\\u2192 ',tx:'   TX ',rx:'   RX ',ret:'\\u2190 ',err:'\\u2717 '};
function num(id){return parseFloat(document.getElementById(id).value)}
async function call(method,kwargs){
  await fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({method,kwargs:kwargs||{}})});
  poll();
}
async function reconfigure(){
  await fetch('/api/reconfigure',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:model.value,transport:transport.value,port:port.value})});
  poll();
}
async function refreshState(){
  const d=await (await fetch('/api/config')).json();
  const el=document.getElementById('state');
  const where=d.transport==='hardware'?('hardware '+(d.port||'no port!')):d.transport;
  el.textContent=(d.connected?'connected':'not connected')+'  \u00b7  '+where;
  // Simulated and offline are never a live pipette, however "connected" they
  // look; only hardware gets the green.
  el.style.color=d.connected&&d.transport==='hardware'?'#6fcf8d'
                :d.transport==='hardware'?'#e2b341':'#8a949e';
  // Keep the form honest about what the server actually holds.
  if(document.activeElement!==port) port.value=d.port;
  model.value=d.model; transport.value=d.transport;
}
async function poll(){
  const r=await fetch('/api/log?after='+after);
  const d=await r.json();
  const el=document.getElementById('log');
  for(const e of d.entries){
    after=e.seq;
    const line=document.createElement('div');
    line.className=e.kind;
    line.textContent=(PREFIX[e.kind]||'')+e.text;
    el.appendChild(line);
  }
  if(d.entries.length){el.scrollTop=el.scrollHeight;refreshState();}
}
async function init(){
  const r=await fetch('/api/config');const d=await r.json();
  for(const m of d.models){const o=document.createElement('option');o.value=o.textContent=m;model.appendChild(o)}
  model.value=d.model;transport.value=d.transport;port.value=d.port;
  setInterval(poll,500);poll();refreshState();
}
init();
</script>
"""


def make_handler(bench: Bench):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # the bench log is the interesting one

        def _send(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if self.path.startswith("/api/log"):
                after = 0
                if "after=" in self.path:
                    after = int(self.path.split("after=")[1].split("&")[0])
                return self._send({"entries": bench.entries(after)})
            if self.path.startswith("/api/config"):
                return self._send({
                    "models": sorted(PICUS2_MODELS),
                    "model": bench.model,
                    "transport": bench.transport,
                    "port": bench.port,
                    "connected": bench.connected,
                })
            page = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            body = self._body()
            if self.path == "/api/call":
                return self._send(bench.call(body["method"], body.get("kwargs") or {}))
            if self.path == "/api/reconfigure":
                return self._send(bench.reconfigure(
                    body["model"], body["transport"], body.get("port") or "",
                ))
            self._send({"ok": False, "error": "unknown endpoint"}, status=404)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="picus2_1ch_1000", choices=sorted(PICUS2_MODELS))
    parser.add_argument(
        "--transport", default="simulated",
        choices=["simulated", "hardware", "offline"],
    )
    parser.add_argument("--port", default="", help="serial port for --transport hardware")
    parser.add_argument("--http-port", type=int, default=8770)
    args = parser.parse_args()

    bench = Bench(args.model, args.transport, args.port)
    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(bench))
    print(f"Picus 2 bench on http://127.0.0.1:{args.http_port}  "
          f"(model={args.model}, transport={args.transport}, port={args.port or '-'})")
    server.serve_forever()


if __name__ == "__main__":
    main()
