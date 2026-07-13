"""Settings API for Zoo configuration such as the local config directory."""

from pathlib import Path
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from zoo.config import get_settings, persist_user_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    config_dir: str


class UpdateSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_dir: str


@router.get("")
def get_current_settings() -> SettingsResponse:
    return SettingsResponse(config_dir=str(get_settings().configs_dir))


@router.put("")
def update_settings(body: UpdateSettingsRequest) -> SettingsResponse:
    path = Path(body.config_dir).expanduser()
    if not path.is_dir():
        raise HTTPException(400, f"Directory does not exist: {body.config_dir}")

    resolved = path.resolve()
    try:
        persist_user_settings(config_dir=resolved)
    except OSError as exc:
        raise HTTPException(500, f"Failed to persist settings: {exc}") from exc

    get_settings().config_dir = resolved
    return SettingsResponse(config_dir=str(get_settings().configs_dir))


@router.post("/browse")
def browse_directory() -> SettingsResponse:
    """Open a native directory picker and return the selected path."""
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Select config directory")'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(400, f"Directory picker failed: {exc}") from exc
        if result.returncode != 0:
            raise HTTPException(400, "No directory selected")
        selected = result.stdout.strip().rstrip("/")
    else:
        script = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "selected = filedialog.askdirectory(title='Select config directory')\n"
            "root.destroy()\n"
            "print(selected)\n"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(400, f"Directory picker failed: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "No directory selected"
            raise HTTPException(400, detail)
        selected = result.stdout.strip()
        if not selected:
            raise HTTPException(400, "No directory selected")

    return SettingsResponse(config_dir=selected)
