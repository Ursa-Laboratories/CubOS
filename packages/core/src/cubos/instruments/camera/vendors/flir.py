"""FLIR high-resolution camera driver via Spinnaker/PySpin.

Ported from PANDA-BEAR's ``panda_lib.hardware.imaging.flir_camera``
(read-only source — never imported from here), including its hard-won
lifecycle care: PySpin segfaults on double-release, so ``disconnect``
DeInits/dels/releases each handle defensively and forces a ``gc.collect()``.
Capture sets the RGB8 pixel format (the camera's built-in color processing)
and saves through OpenCV, because PySpin's own image writer is unreliable.

The Spinnaker SDK is proprietary (free download from Teledyne FLIR, manual
install; see PANDA-BEAR ``src/panda_lib/hardware/imaging/README.md``) and
its Python wheel is not pip-installable, so ``PySpin`` is imported lazily:
constructing an offline ``FlirCamera`` never needs it, and a non-offline
construct without the SDK raises a config error naming the install source.

Pass ``offline=True`` for dry runs — writes a real placeholder PNG so
downstream file handling is exercised without hardware.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cubos.instruments.camera.exceptions import (
    CameraCaptureError,
    CameraConfigError,
    CameraConnectionError,
)
from cubos.instruments.camera.interface import CameraInstrument
from cubos.instruments.camera.placeholder import write_placeholder_png

_GRAB_TIMEOUT_MS = 1000


def _import_pyspin():
    try:
        import PySpin  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CameraConfigError(
            "The FLIR camera driver requires the Spinnaker SDK's PySpin "
            "package, which is proprietary and not pip-installable. Download "
            "both the Spinnaker SDK and the matching Python wheel from "
            "https://www.flir.com/products/spinnaker-sdk/ and install the "
            "wheel into this environment (see PANDA-BEAR "
            "src/panda_lib/hardware/imaging/README.md)."
        ) from exc
    return PySpin


def _import_cv2():
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CameraConfigError(
            "The FLIR camera driver saves images through OpenCV; install "
            "opencv-python (`pip install 'cubos[camera]'`)."
        ) from exc
    return cv2


class FlirCamera(CameraInstrument):
    """FLIR camera (Spinnaker/PySpin) with OpenCV-backed image saving."""

    def __init__(
        self,
        camera_id: int = 0,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs,
    ):
        super().__init__(
            name=name,
            offset_x=offset_x,
            offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        self.camera_id = camera_id
        self._system = None
        self._camera_list = None
        self._camera = None
        self._connected = False

    @staticmethod
    def is_available() -> bool:
        """True when the PySpin wheel is importable in this environment."""
        try:
            import PySpin  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self._connected = True
            self.logger.info("FLIR camera connected (offline)")
            return
        PySpin = _import_pyspin()
        try:
            self._system = PySpin.System.GetInstance()
            self._camera_list = self._system.GetCameras()
            count = self._camera_list.GetSize()
            if count == 0:
                self._release_handles()
                raise CameraConnectionError("No FLIR cameras found.")
            if self.camera_id < count:
                self._camera = self._camera_list[self.camera_id]
            else:
                self.logger.warning(
                    "Camera ID %d out of range (%d found); using first camera",
                    self.camera_id, count,
                )
                self._camera = self._camera_list[0]
            self._camera.Init()
        except PySpin.SpinnakerException as exc:
            self._release_handles()
            raise CameraConnectionError(
                f"Error connecting to FLIR camera: {exc}"
            ) from exc
        self._connected = True
        self.logger.info("Connected to FLIR camera ID %d", self.camera_id)

    def disconnect(self) -> None:
        self._connected = False
        if self._offline:
            self.logger.info("FLIR camera disconnected (offline)")
            return
        self._release_handles()
        self.logger.info("Disconnected from FLIR camera")

    def health_check(self) -> bool:
        if self._offline:
            return True
        return self._connected and self._camera is not None

    # ── CameraInstrument interface ────────────────────────────────────────

    def capture(self, *args: Any, save_path: str = "", **kwargs: Any) -> str:
        """Capture one frame and save it to *save_path*; return the path."""
        if not save_path:
            raise CameraCaptureError("capture requires a save_path.")
        if self._offline:
            return str(write_placeholder_png(save_path))
        if not self._connected or self._camera is None:
            raise CameraCaptureError("Cannot capture image: camera not connected.")

        PySpin = _import_pyspin()
        cv2 = _import_cv2()
        try:
            # Built-in color processing: RGB8 straight off the camera.
            nodemap = self._camera.GetNodeMap()
            pixel_format = PySpin.CEnumerationPtr(nodemap.GetNode("PixelFormat"))
            if PySpin.IsAvailable(pixel_format) and PySpin.IsWritable(pixel_format):
                rgb8_entry = pixel_format.GetEntryByName("RGB8")
                if rgb8_entry and PySpin.IsAvailable(rgb8_entry):
                    pixel_format.SetIntValue(rgb8_entry.GetValue())

            self._camera.BeginAcquisition()
            try:
                image_result = self._camera.GetNextImage(_GRAB_TIMEOUT_MS)
                try:
                    if image_result.IsIncomplete():
                        raise CameraCaptureError(
                            "Image incomplete with status "
                            f"{image_result.GetImageStatus()}"
                        )
                    image_data = image_result.GetNDArray()
                finally:
                    image_result.Release()
            finally:
                try:
                    self._camera.EndAcquisition()
                except PySpin.SpinnakerException:
                    pass
        except PySpin.SpinnakerException as exc:
            raise CameraCaptureError(
                f"Error capturing image from FLIR camera: {exc}"
            ) from exc

        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(target), cv2.cvtColor(image_data, cv2.COLOR_RGB2BGR)):
            raise CameraCaptureError(f"Failed to write image to {target}")
        self.logger.info("Image saved to %s", target)
        return str(target)

    # ── Private helpers ───────────────────────────────────────────────────

    def _release_handles(self) -> None:
        """Tear down PySpin handles in strict reverse order.

        PySpin segfaults if the system instance is released while camera or
        list handles are alive, and warns loudly on leaked references — the
        ``del`` calls and final ``gc.collect()`` are load-bearing.
        """
        import gc

        try:
            PySpin = _import_pyspin()
        except CameraConfigError:
            return
        if self._camera is not None:
            try:
                self._camera.DeInit()
            except PySpin.SpinnakerException as exc:
                self.logger.warning("Error de-initializing camera: %s", exc)
            finally:
                del self._camera
                self._camera = None
        if self._camera_list is not None:
            try:
                self._camera_list.Clear()
            except PySpin.SpinnakerException as exc:
                self.logger.warning("Error clearing camera list: %s", exc)
            finally:
                del self._camera_list
                self._camera_list = None
        if self._system is not None:
            try:
                self._system.ReleaseInstance()
            except PySpin.SpinnakerException as exc:
                self.logger.warning("Error releasing system instance: %s", exc)
            finally:
                del self._system
                self._system = None
        gc.collect()
