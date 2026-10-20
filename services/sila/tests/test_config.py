from dataclasses import replace
from pathlib import Path

import pytest

from cubos_sila.config import ConfigurationError, Settings, load_settings


UUID = "455c09ee-3662-4103-befc-46b7cc14b35d"


def config(tmp_path: Path, extra: str = "") -> Path:
    for name in ("gantry", "deck", "protocol"):
        (tmp_path / f"{name}.yaml").write_text(f"{name}: {{}}\n")
    path = tmp_path / "settings.yaml"
    path.write_text(
        f"server_uuid: {UUID}\n"
        "presets:\n"
        "  demo:\n"
        "    gantry_file: gantry.yaml\n"
        "    deck_file: deck.yaml\n"
        "    protocol_file: protocol.yaml\n"
        + extra
    )
    return path


def test_relative_files_are_loaded_as_complete_immutable_bundle(tmp_path, monkeypatch):
    path = config(tmp_path)
    monkeypatch.chdir("/")
    settings = load_settings(path)
    assert settings.api_url == "http://127.0.0.1:8742"
    assert not settings.allow_hardware
    preset, = settings.presets
    assert preset.mock_mode
    assert preset.bundle.gantry_config == "gantry: {}\n"
    assert set(preset.bundle.as_payload()) == {"gantry_config", "deck_config", "protocol_yaml"}
    before = preset.bundle.sha256
    (tmp_path / "protocol.yaml").write_text("changed: {}\n")
    assert preset.bundle.sha256 == before
    assert load_settings(path).presets[0].bundle.sha256 != before


def test_hardware_needs_explicit_authorization(tmp_path):
    path = config(tmp_path, "    mock_mode: false\n")
    with pytest.raises(ConfigurationError, match="hardware presets"):
        load_settings(path)
    assert load_settings(path, allow_hardware=True).allow_hardware
    path.write_text(path.read_text() + "allow_hardware: true\n")
    assert load_settings(path).allow_hardware
    with pytest.raises(ConfigurationError, match="hardware presets"):
        load_settings(path, allow_hardware=False)


def test_secret_env_and_file_are_not_in_repr(tmp_path, monkeypatch):
    path = config(tmp_path, "api_token_env: SILA_TEST_TOKEN\n")
    monkeypatch.setenv("SILA_TEST_TOKEN", "supersecret")
    settings = load_settings(path)
    assert settings.api_token == "supersecret"
    assert "supersecret" not in repr(settings)
    path.write_text(path.read_text().replace("api_token_env: SILA_TEST_TOKEN", "api_token_file: secret"))
    (tmp_path / "secret").write_text("file-secret\n")
    assert load_settings(path).api_token == "file-secret"


@pytest.mark.parametrize("extra, match", [
    ("api_token_env: ABSENT_TOKEN\n", "empty"),
    ("api_token_env: X\napi_token_file: token\n", "only one"),
    ("api_token: plaintext\n", "unsupported"),
    ("other: value\n", "unsupported"),
    ("request_timeout_s: 0\n", "positive finite"),
    ("request_timeout_s: .nan\n", "positive finite"),
    ("poll_interval_s: true\n", "positive finite"),
    ("max_response_bytes: -1\n", "positive integer"),
    ("allow_hardware: 'false'\n", "boolean"),
    ("host: 0.0.0.0\n", "requires certificate"),
    ("api_url: http://user:secret@example.org\n", "without credentials"),
    ("api_url: http://example.org?token=secret\n", "without credentials"),
    ("api_url: http://example.org:bad\n", "invalid port"),
    ("port: 70000\n", "between"),
])
def test_invalid_config_is_rejected(tmp_path, monkeypatch, extra, match):
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match=match):
        load_settings(config(tmp_path, extra))


@pytest.mark.parametrize("text", ["[]", "bad: [", "null"])
def test_invalid_root(tmp_path, text):
    path = tmp_path / "invalid.yaml"
    path.write_text(text)
    with pytest.raises(ConfigurationError):
        load_settings(path)


def test_missing_identity_and_bundle_files(tmp_path):
    path = config(tmp_path)
    path.write_text(path.read_text().replace(f"server_uuid: {UUID}\n", ""))
    with pytest.raises(ConfigurationError, match="server_uuid"):
        load_settings(path)
    path = config(tmp_path)
    (tmp_path / "deck.yaml").unlink()
    with pytest.raises(ConfigurationError, match="cannot read deck_file"):
        load_settings(path)


def test_empty_or_invalid_yaml_bundle(tmp_path):
    path = config(tmp_path)
    for text in ("", "[]", "bad: ["):
        (tmp_path / "protocol.yaml").write_text(text)
        with pytest.raises(ConfigurationError, match="protocol_file"):
            load_settings(path)


def test_port_zero_and_stable_identity():
    assert Settings(UUID, port=0).port == 0
    with pytest.raises(ConfigurationError, match="UUID"):
        Settings("invalid")
    with pytest.raises(ConfigurationError, match="positive integer"):
        replace(Settings(UUID), max_artifact_bytes=False)


def test_tls_pair_and_nonloopback_binding(tmp_path):
    path = config(tmp_path, "host: 0.0.0.0\ncertificate: cert.pem\nprivate_key: key.pem\n")
    (tmp_path / "cert.pem").write_text("cert")
    (tmp_path / "key.pem").write_text("key")
    assert load_settings(path).certificate == tmp_path / "cert.pem"
    with pytest.raises(ConfigurationError, match="together"):
        replace(Settings(UUID), certificate=tmp_path / "cert.pem")


def test_bundle_limits_and_bad_preset_fields(tmp_path):
    path = config(tmp_path, "max_response_bytes: 20\n")
    with pytest.raises(ConfigurationError, match="bundle exceeds"):
        load_settings(path)
    path = config(tmp_path, "    unknown: true\n")
    with pytest.raises(ConfigurationError, match="unsupported"):
        load_settings(path)
