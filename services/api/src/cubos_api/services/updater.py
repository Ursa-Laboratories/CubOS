"""Git-backed update checks and detached appliance update launches."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from pydantic import BaseModel

from cubos_api.config import get_settings


UPDATE_CACHE_TTL_SECONDS = 3600
GIT_TIMEOUT_SECONDS = 30


def _discover_repo_dir() -> Path:
    source = Path(__file__).resolve()
    for candidate in source.parents:
        if (candidate / ".git").exists():
            return candidate
    return source.parent


REPO_DIR = _discover_repo_dir()


class UpdateLaunchError(RuntimeError):
    """Raised when the detached updater cannot be launched."""


class UpdateStatus(BaseModel):
    current_sha: str
    latest_sha: str
    commits_behind: int
    update_available: bool
    checked_at: float
    summary: list[str]
    error: str | None


_cache: UpdateStatus | None = None
_cache_lock = threading.Lock()


def _repo_dir() -> Path:
    configured = get_settings().update_repo_dir
    return configured.expanduser().resolve() if configured is not None else REPO_DIR


def _run_git(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return completed.stdout.strip()


def _git(repo: Path, *args: str) -> str:
    return _run_git(["git", "-C", str(repo), *args])


def _failure_status(exc: BaseException, *, current_sha: str = "") -> UpdateStatus:
    detail = ""
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or exc.stdout or "").strip()
    if not detail:
        detail = str(exc)
    return UpdateStatus(
        current_sha=current_sha,
        latest_sha="",
        commits_behind=0,
        update_available=False,
        checked_at=time.time(),
        summary=[],
        error=detail,
    )


def check_for_update(*, refresh: bool = False) -> UpdateStatus:
    """Return origin update status without propagating git failures."""
    global _cache

    repo = _repo_dir()
    if not (repo / ".git").exists():
        return UpdateStatus(
            current_sha="",
            latest_sha="",
            commits_behind=0,
            update_available=False,
            checked_at=time.time(),
            summary=[],
            error="not a git checkout",
        )

    try:
        current_sha = _git(repo, "rev-parse", "HEAD")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return _failure_status(exc)

    now = time.time()
    with _cache_lock:
        if (
            not refresh
            and _cache is not None
            and _cache.current_sha == current_sha
            and now - _cache.checked_at < UPDATE_CACHE_TTL_SECONDS
        ):
            return _cache.model_copy(deep=True)

        branch = get_settings().update_branch
        try:
            _git(repo, "fetch", "--quiet", "origin", branch)
            latest_sha = _git(repo, "rev-parse", f"origin/{branch}")
            commits_behind = int(
                _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}")
            )
            log_output = _git(repo, "log", "--oneline", f"HEAD..origin/{branch}")
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
            ValueError,
        ) as exc:
            return _failure_status(exc, current_sha=current_sha)

        status = UpdateStatus(
            current_sha=current_sha,
            latest_sha=latest_sha,
            commits_behind=commits_behind,
            update_available=commits_behind > 0,
            checked_at=time.time(),
            summary=log_output.splitlines()[:10],
            error=None,
        )
        _cache = status
        return status.model_copy(deep=True)


def apply_update(target_sha: str) -> None:
    """Launch the updater independently of the API service process."""
    settings = get_settings()
    repo = _repo_dir()
    configured_script = settings.update_script
    script = (
        configured_script.expanduser().resolve()
        if configured_script is not None
        else repo / "deploy" / "pi" / "update.sh"
    )
    if not script.is_file():
        raise UpdateLaunchError(f"update script not found: {script}")

    try:
        if shutil.which("systemd-run"):
            # Run the updater as the service user, never as root: repo code
            # (pip/npm build hooks) must not execute with elevated privileges.
            # Root is only borrowed inside the script for the single
            # "systemctl restart" command via its own sudoers entry.
            subprocess.run(
                [
                    "sudo",
                    "systemd-run",
                    f"--uid={getpass.getuser()}",
                    "--unit=cubos-update",
                    "--collect",
                    str(script),
                    target_sha,
                ],
                check=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
            return

        log_path = Path.home() / ".cubos" / "update.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["CUBOS_SERVICE"] = settings.update_service
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                [str(script), target_sha],
                start_new_session=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=environment,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateLaunchError(f"failed to launch updater: {exc}") from exc


def reset_update_cache() -> None:
    """Clear cached update metadata."""
    global _cache
    with _cache_lock:
        _cache = None
