import json
import os
from pathlib import Path
from typing import Any, List

from data import default_database_path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
USER_SETTINGS_FILE = Path.home() / ".zoo" / "settings.json"


def _user_settings_file() -> Path:
    override = os.environ.get("ZOO_SETTINGS_FILE")
    if override:
        return Path(override).expanduser()
    return USER_SETTINGS_FILE


def _env_config_dir_is_set() -> bool:
    return "ZOO_CONFIG_DIR" in os.environ


def _load_user_settings() -> dict[str, Any]:
    if _env_config_dir_is_set():
        return {}
    path = _user_settings_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    config_dir = data.get("config_dir")
    if not isinstance(config_dir, str) or not config_dir:
        return {}
    return {"config_dir": Path(config_dir)}


def persist_user_settings(*, config_dir: Path) -> None:
    path = _user_settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"config_dir": str(config_dir.expanduser().resolve())}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


class ZooSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZOO_",
        extra="ignore",
        validate_assignment=True,
    )

    config_dir: Path = DEFAULT_CONFIG_DIR
    host: str = "127.0.0.1"
    port: int = 8742
    open_browser: bool = True
    data_db_path: Path = default_database_path()
    run_dir: Path = Path.home() / ".zoo" / "runs"
    api_token: SecretStr | None = None
    allowed_commands: List[str] = Field(default_factory=list)
    allowed_instruments: List[str] = Field(default_factory=list)
    expected_gantry_sha256: str | None = None
    expected_deck_sha256: str | None = None
    # Extra Host/Origin values accepted by the Origin/Host-checking middleware,
    # on top of the configured host:port and localhost/127.0.0.1 equivalents.
    # Production should leave this empty; tests add "testserver" (the Host
    # header httpx's ASGI transport sends) via zoo/tests conftest fixtures.
    trusted_hosts: List[str] = Field(default_factory=list)

    def __init__(self, **data):
        if "config_dir" not in data:
            data = {**_load_user_settings(), **data}
        super().__init__(**data)
        self.ensure_config_dir()

    @property
    def configs_dir(self) -> Path:
        return self.ensure_config_dir()

    def ensure_config_dir(self) -> Path:
        path = self.config_dir.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        self.config_dir = path
        return path

    def ensure_run_dir(self) -> Path:
        path = self.run_dir.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        self.run_dir = path
        return path


# Shared singleton — all routers must use this instance.
_settings = ZooSettings()


def get_settings() -> ZooSettings:
    return _settings
