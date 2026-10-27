"""Local deployment settings and complete, immutable protocol presets."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import yaml


class ConfigurationError(ValueError):
    """The local server configuration cannot be used safely."""


@dataclass(frozen=True)
class ProtocolBundle:
    gantry_config: str
    deck_config: str
    protocol_yaml: str

    def as_payload(self) -> dict[str, str]:
        return {
            "gantry_config": self.gantry_config,
            "deck_config": self.deck_config,
            "protocol_yaml": self.protocol_yaml,
        }

    @property
    def sha256(self) -> str:
        content = json.dumps(self.as_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProtocolPreset:
    name: str
    bundle: ProtocolBundle
    description: str = ""
    mock_mode: bool = True


@dataclass(frozen=True)
class Settings:
    server_uuid: str
    api_url: str = "http://127.0.0.1:8742"
    api_token: str | None = field(default=None, repr=False)
    allow_hardware: bool = False
    request_timeout_s: float = 10.0
    poll_interval_s: float = 0.25
    max_artifact_bytes: int = 16 * 1024 * 1024
    max_response_bytes: int = 4 * 1024 * 1024
    presets: tuple[ProtocolPreset, ...] = ()
    server_name: str = "CubOS"
    host: str = "127.0.0.1"
    port: int = 50051
    certificate: Path | None = None
    private_key: Path | None = field(default=None, repr=False)
    discovery: bool = False

    def __post_init__(self) -> None:
        try:
            UUID(self.server_uuid)
        except (ValueError, TypeError, AttributeError):
            raise ConfigurationError("server_uuid must be an explicit stable UUID") from None
        if not isinstance(self.api_url, str):
            raise ConfigurationError("api_url must be an HTTP(S) origin without credentials")
        try:
            parsed = urlsplit(self.api_url)
        except ValueError:
            raise ConfigurationError("api_url must be a valid HTTP(S) origin") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ConfigurationError("api_url must be an HTTP(S) origin without credentials")
        try:
            parsed.port
        except ValueError:
            raise ConfigurationError("api_url has an invalid port") from None
        for name in ("request_timeout_s", "poll_interval_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive finite number")
        for name in ("max_artifact_bytes", "max_response_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ConfigurationError("port must be between 0 and 65535")
        for name in ("allow_hardware", "discovery"):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f"{name} must be a boolean")
        if self.api_token is not None and (
            not isinstance(self.api_token, str) or not self.api_token
            or any(char.isspace() for char in self.api_token)
        ):
            raise ConfigurationError("API token must be a nonempty string without whitespace")
        if not isinstance(self.host, str) or not self.host or not isinstance(self.server_name, str) or not self.server_name:
            raise ConfigurationError("host and server_name must be nonempty strings")
        if bool(self.certificate) != bool(self.private_key):
            raise ConfigurationError("certificate and private_key must be configured together")
        try:
            loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            loopback = self.host == "localhost"
        if not loopback and not self.certificate:
            raise ConfigurationError("non-loopback SiLA binding requires certificate and private_key")
        names = set()
        for preset in self.presets:
            if not preset.name or preset.name in names:
                raise ConfigurationError("preset names must be nonempty and unique")
            names.add(preset.name)
            if type(preset.mock_mode) is not bool:
                raise ConfigurationError("preset mock_mode must be a boolean")
            if not preset.mock_mode and not self.allow_hardware:
                raise ConfigurationError("hardware presets require allow_hardware: true")


def _read(path: Path, label: str, *, limit: int = 4 * 1024 * 1024) -> str:
    try:
        with path.open("rb") as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise ConfigurationError(f"{label} exceeds the configured byte limit")
        return content.decode("utf-8")
    except (OSError, UnicodeError):
        raise ConfigurationError(f"cannot read {label} as UTF-8") from None


def load_settings(path: str | Path, *, allow_hardware: bool | None = None) -> Settings:
    path = Path(path).expanduser().resolve()
    try:
        data = yaml.safe_load(_read(path, "configuration"))
    except yaml.YAMLError:
        raise ConfigurationError("configuration must contain valid YAML") from None
    if not isinstance(data, dict):
        raise ConfigurationError("configuration must be a mapping")
    allowed = set(Settings.__dataclass_fields__) - {"api_token"}
    allowed.update({"api_token_env", "api_token_file"})
    if set(data) - allowed:
        raise ConfigurationError("configuration contains unsupported fields")
    values = dict(data)
    if allow_hardware is not None:
        values["allow_hardware"] = allow_hardware
    token_env = values.pop("api_token_env", "CUBOS_API_TOKEN")
    token_file = values.pop("api_token_file", None)
    if token_file is not None and "api_token_env" in data:
        raise ConfigurationError("configure only one of api_token_env and api_token_file")

    def resolve(value: object, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"{label} must be a nonempty path")
        result = Path(value).expanduser()
        return (path.parent / result).resolve() if not result.is_absolute() else result.resolve()

    if token_file is not None:
        token = _read(resolve(token_file, "api_token_file"), "API token file", limit=65536).strip()
        if not token:
            raise ConfigurationError("API token file must not be empty")
    else:
        if not isinstance(token_env, str) or not token_env:
            raise ConfigurationError("api_token_env must be a nonempty environment variable name")
        token = os.environ.get(token_env) or None
        if "api_token_env" in data and not token:
            raise ConfigurationError("configured API token environment variable is empty")
    if token is not None and any(char.isspace() for char in token):
        raise ConfigurationError("API token must not contain whitespace")
    values["api_token"] = token
    for name in ("certificate", "private_key"):
        if values.get(name) is not None:
            values[name] = resolve(values[name], name)
            _read(values[name], name, limit=1024 * 1024)
    catalog = values.pop("presets", {})
    if not isinstance(catalog, dict):
        raise ConfigurationError("presets must be a mapping of names to preset settings")
    presets = []
    bundle_limit = values.get("max_response_bytes", 4 * 1024 * 1024)
    if type(bundle_limit) is not int or bundle_limit <= 0:
        raise ConfigurationError("max_response_bytes must be a positive integer")
    for name, entry in catalog.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise ConfigurationError("each preset must have a nonempty name and mapping")
        fields = {"gantry_file", "deck_file", "protocol_file", "description", "mock_mode"}
        if set(entry) - fields:
            raise ConfigurationError("preset contains unsupported fields")
        contents = []
        for key in ("gantry_file", "deck_file", "protocol_file"):
            content = _read(resolve(entry.get(key), key), key, limit=bundle_limit)
            try:
                document = yaml.safe_load(content)
            except yaml.YAMLError:
                raise ConfigurationError(f"{key} must contain valid YAML") from None
            if not isinstance(document, dict) or not document:
                raise ConfigurationError(f"{key} must contain a nonempty YAML mapping")
            contents.append(content)
        description = entry.get("description", "")
        if not isinstance(description, str):
            raise ConfigurationError("preset description must be a string")
        bundle = ProtocolBundle(*contents)
        if len(json.dumps(bundle.as_payload()).encode("utf-8")) > bundle_limit:
            raise ConfigurationError("complete preset bundle exceeds max_response_bytes")
        presets.append(ProtocolPreset(name, bundle, description, entry.get("mock_mode", True)))
    values["presets"] = tuple(presets)
    if "server_uuid" not in values:
        raise ConfigurationError("server_uuid must be an explicit stable UUID")
    return Settings(**values)
