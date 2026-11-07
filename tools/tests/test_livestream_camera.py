"""Focused tests for the CubOS camera stream's frame bookkeeping."""

from __future__ import annotations

import importlib.util
import hashlib
import threading
import time
from argparse import Namespace
from pathlib import Path
from urllib.request import urlopen


_MODULE_PATH = Path(__file__).parents[1] / "livestream_camera.py"
_SPEC = importlib.util.spec_from_file_location("livestream_camera", _MODULE_PATH)
assert _SPEC and _SPEC.loader
camera = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(camera)


def test_broadcast_keeps_only_latest_frame_per_subscriber() -> None:
    broadcaster = camera.FrameBroadcaster(["ffmpeg"])
    subscriber = broadcaster.subscribe()

    broadcaster._broadcast(b"first")
    broadcaster._broadcast(b"second")

    assert subscriber.wait(timeout=0) == b"second"
    assert subscriber.wait(timeout=0) is None


def test_status_distinguishes_repeated_pixels_from_no_frames() -> None:
    broadcaster = camera.FrameBroadcaster(["ffmpeg"])
    assert broadcaster.status()["state"] == "no_frames"
    assert broadcaster.status()["source_repeating"] is False

    broadcaster._broadcast(b"same image")
    broadcaster._broadcast(b"same image")
    status = broadcaster.status()

    assert status["state"] == "source_repeating"
    assert status["total_frames"] == 2
    assert status["unique_frames"] == 1
    assert status["source_repeating"] is True
    assert status["frame_id"] == 2


def test_new_pixels_clear_source_repeating_flag() -> None:
    broadcaster = camera.FrameBroadcaster(["ffmpeg"])
    broadcaster._broadcast(b"same image")
    broadcaster._broadcast(b"same image")
    broadcaster._broadcast(b"changed image")

    status = broadcaster.status()
    assert status["state"] == "receiving"
    assert status["source_repeating"] is False
    assert status["unique_frames"] == 2
    assert status["changed_frames"] == 1


def test_ffmpeg_output_is_paced_at_requested_rate() -> None:
    args = Namespace(
        input_format="avfoundation",
        fps=30,
        width=1920,
        height=1080,
        device="0",
        quality=5,
    )

    command = camera.build_ffmpeg_cmd(args)

    assert command[command.index("-r") + 1] == "30"
    assert command[command.index("-i") + 1] == "0:none"


def test_status_reports_stale_source_after_frames_stop_arriving() -> None:
    broadcaster = camera.FrameBroadcaster(["ffmpeg"])
    broadcaster._broadcast(b"frame")
    broadcaster._latest_received_at = time.time() - camera.STALE_AFTER_SECONDS - 0.1

    status = broadcaster.status()

    assert status["state"] == "stale"
    assert status["process_running"] is False
    assert status["source_repeating"] is False


def test_frame_endpoint_includes_identity_headers() -> None:
    broadcaster = camera.FrameBroadcaster(["ffmpeg"])
    broadcaster._broadcast(b"jpeg payload")
    server = camera.ThreadingHTTPServer(("127.0.0.1", 0), camera.make_handler(broadcaster))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/frame.jpg") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/jpeg"
            assert response.headers["X-Frame-Id"] == "1"
            assert response.headers["X-Frame-Hash"] == hashlib.sha256(b"jpeg payload").hexdigest()
            assert response.read() == b"jpeg payload"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
