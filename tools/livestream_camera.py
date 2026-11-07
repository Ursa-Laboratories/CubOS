#!/usr/bin/env python
"""Livestream a locally attached camera over HTTP as MJPEG.

Spawns ffmpeg to grab frames from a camera device and serves them to any
browser as a ``multipart/x-mixed-replace`` MJPEG stream -- no browser plugins,
no extra Python deps beyond the stdlib. Meant for pointing a USB camera at a
CubOS deck/instrument during a run and watching it live from another machine
on the network.

Requires ffmpeg on PATH (``brew install ffmpeg``). Uses macOS AVFoundation by
default; pass --input-format to target a different platform (e.g. v4l2 on
Linux, dshow on Windows) with a device string that matches that format.

Usage:
    python tools/livestream_camera.py --list-devices
    python tools/livestream_camera.py --device 1                 # USB Camera, :8090
    python tools/livestream_camera.py --device "USB Camera" --port 8091
    python tools/livestream_camera.py --device 1 --fps 15 --width 1280 --height 720

Not part of the shipped package: a bench utility that lives beside the driver.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOUNDARY = "cubosframe"
STALE_AFTER_SECONDS = 2.0


class FrameSubscriber:
    """A bounded latest-frame slot for one MJPEG client."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: bytes | None = None
        self._closed = False

    def publish(self, frame: bytes) -> None:
        with self._condition:
            self._frame = frame
            self._condition.notify()

    def wait(self, timeout: float = 1.0) -> bytes | None:
        with self._condition:
            if self._frame is None and not self._closed:
                self._condition.wait(timeout)
            frame = self._frame
            self._frame = None
            return frame

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


def list_devices() -> None:
    proc = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    # ffmpeg reports the device list on stderr and always "fails" for this probe.
    for line in proc.stderr.splitlines():
        if "AVFoundation" in line and ("video devices" in line or "]" in line and "[" in line.split("]", 1)[-1]):
            print(line.split("] ", 1)[-1])


class FrameBroadcaster:
    """Runs ffmpeg once, fans its MJPEG output out to every connected client."""

    def __init__(self, ffmpeg_cmd: list[str]):
        self._cmd = ffmpeg_cmd
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._clients: list[FrameSubscriber] = []
        self._latest_error: str | None = None
        self._latest_frame: bytes | None = None
        self._latest_frame_id = 0
        self._latest_received_at: float | None = None
        self._latest_hash: str | None = None
        self._total_frames = 0
        self._recent_hashes: deque[str] = deque(maxlen=256)
        self._changed_frames = 0
        self._consecutive_duplicate_frames = 0
        self._first_received_at: float | None = None
        self._process_exited_at: float | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_frames, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for raw in self._proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._latest_error = line

    def _read_frames(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        buf = b""
        marker_end = b"\xff\xd9"  # JPEG end-of-image
        marker_start = b"\xff\xd8"  # JPEG start-of-image
        while True:
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            end = buf.find(marker_end)
            if end == -1:
                continue
            start = buf.find(marker_start)
            if start == -1 or start > end:
                buf = buf[end + 2 :]
                continue
            frame = buf[start : end + 2]
            buf = buf[end + 2 :]
            self._broadcast(frame)
        sys.stderr.write(
            f"ffmpeg exited (last message: {self._latest_error or 'unknown'})\n"
        )
        self._process_exited_at = time.time()

    def _broadcast(self, frame: bytes) -> None:
        received_at = time.time()
        frame_hash = hashlib.sha256(frame).hexdigest()
        with self._lock:
            previous_hash = self._latest_hash
            self._latest_frame = frame
            self._latest_frame_id += 1
            self._latest_received_at = received_at
            self._latest_hash = frame_hash
            self._total_frames += 1
            if frame_hash == previous_hash:
                self._consecutive_duplicate_frames += 1
            else:
                self._consecutive_duplicate_frames = 0
                if previous_hash is not None:
                    self._changed_frames += 1
            self._recent_hashes.append(frame_hash)
            for queue in self._clients:
                queue.publish(frame)
            if self._first_received_at is None:
                self._first_received_at = received_at

    def subscribe(self) -> FrameSubscriber:
        queue = FrameSubscriber()
        with self._lock:
            self._clients.append(queue)
        return queue

    def unsubscribe(self, queue: FrameSubscriber) -> None:
        with self._lock:
            if queue in self._clients:
                self._clients.remove(queue)
            queue.close()

    def latest_frame(self) -> tuple[bytes, int, float, str] | None:
        with self._lock:
            if (
                self._latest_frame is None
                or self._latest_received_at is None
                or self._latest_hash is None
            ):
                return None
            return (
                self._latest_frame,
                self._latest_frame_id,
                self._latest_received_at,
                self._latest_hash,
            )

    def status(self) -> dict[str, object]:
        now = time.time()
        with self._lock:
            received_at = self._latest_received_at
            process = self._proc
            process_running = process is not None and process.poll() is None
            if received_at is None:
                state = "starting" if process_running else "no_frames"
            elif now - received_at > STALE_AFTER_SECONDS:
                state = "stale"
            elif self._consecutive_duplicate_frames:
                state = "source_repeating"
            else:
                state = "receiving"
            elapsed = (
                now - self._first_received_at
                if self._first_received_at is not None
                else 0.0
            )
            return {
                "state": state,
                "process_running": process_running,
                "latest_received_at": received_at,
                "frame_id": self._latest_frame_id,
                "frame_hash": self._latest_hash,
                "total_frames": self._total_frames,
                "unique_frames": len(set(self._recent_hashes)),
                "recent_hash_window": self._recent_hashes.maxlen,
                "changed_frames": self._changed_frames,
                "consecutive_duplicate_frames": self._consecutive_duplicate_frames,
                "source_repeating": self._consecutive_duplicate_frames > 0,
                "fps": self._total_frames / elapsed if elapsed > 0 else 0.0,
                "stale_after_seconds": STALE_AFTER_SECONDS,
                "latest_error": self._latest_error,
                "process_exited_at": self._process_exited_at,
            }

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


def make_handler(broadcaster: FrameBroadcaster):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # quiet the default access log
            pass

        def do_GET(self) -> None:
            if self.path not in ("/", "/stream"):
                if self.path == "/frame.jpg":
                    latest = broadcaster.latest_frame()
                    if latest is None:
                        self.send_response(503)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"state":"no_frames"}')
                        return
                    frame, frame_id, captured_at, frame_hash = latest
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Frame-Id", str(frame_id))
                    self.send_header("X-Captured-At", str(captured_at))
                    self.send_header("X-Frame-Hash", frame_hash)
                    self.end_headers()
                    self.wfile.write(frame)
                    return
                if self.path == "/status":
                    body = json.dumps(broadcaster.status()).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()
                return
            if self.path == "/":
                body = (
                    b"<html><body style='margin:0;background:#111'>"
                    b"<img src='/stream' style='max-width:100%;display:block;margin:auto'>"
                    b"</body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(200)
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
            )
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            queue = broadcaster.subscribe()
            try:
                while True:
                    frame = queue.wait()
                    if frame is None:
                        continue
                    self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                broadcaster.unsubscribe(queue)

    return Handler


def build_ffmpeg_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        "ffmpeg",
        "-f",
        args.input_format,
        "-framerate",
        str(args.fps),
    ]
    if args.width and args.height:
        cmd += ["-video_size", f"{args.width}x{args.height}"]
    cmd += [
        "-i",
        f"{args.device}:none" if args.input_format == "avfoundation" else args.device,
        "-r",
        str(args.fps),
        "-f",
        "mjpeg",
        "-q:v",
        str(args.quality),
        "-an",
        "pipe:1",
    ]
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="list cameras and exit")
    parser.add_argument("--device", default="1", help="ffmpeg device index or name (default: 1)")
    parser.add_argument("--input-format", default="avfoundation", help="ffmpeg -f value (default: avfoundation, macOS)")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--quality", type=int, default=5, help="ffmpeg mjpeg -q:v, lower = better quality (2-10 typical)")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it with: brew install ffmpeg")

    if args.list_devices:
        list_devices()
        return

    cmd = build_ffmpeg_cmd(args)
    print("ffmpeg:", " ".join(cmd))

    broadcaster = FrameBroadcaster(cmd)
    broadcaster.start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(broadcaster))
    print(f"Livestream at http://{args.host}:{args.port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        broadcaster.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
