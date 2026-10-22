import pytest

from cubos_sila import __version__
from cubos_sila import __main__ as cli
from cubos_sila.config import ConfigurationError


@pytest.mark.parametrize("allow,argv", [(False, []), (True, ["--allow-hardware"])])
def test_cli_requires_explicit_hardware_opt_in(monkeypatch, tmp_path, allow, argv):
    config = tmp_path / "config.yaml"
    observed = {}
    settings = object()

    def load(path, *, allow_hardware):
        observed.update(path=path, allow_hardware=allow_hardware)
        return settings

    async def serve(value):
        observed["settings"] = value

    monkeypatch.setattr(cli, "load_settings", load)
    monkeypatch.setattr(cli, "serve", serve)
    assert cli.main(["--config", str(config), *argv]) == 0
    assert observed == {"path": config, "allow_hardware": allow, "settings": settings}


def test_invalid_configuration_fails_before_server_creation(monkeypatch, tmp_path, capsys):
    def load(*args, **kwargs):
        raise ConfigurationError("server_uuid must be an explicit stable UUID")

    monkeypatch.setattr(cli, "load_settings", load)
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", str(tmp_path / "invalid.yaml")])
    assert error.value.code == 2
    assert "server_uuid" in capsys.readouterr().err


def test_version_needs_no_configuration(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--version"])
    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


async def test_startup_failure_is_reported_and_backend_is_closed(monkeypatch):
    calls = []

    class App:
        async def start(self):
            raise RuntimeError("cannot bind port")

        async def stop(self):
            calls.append("stopped")

    monkeypatch.setattr(cli, "create_app", lambda settings: App())
    with pytest.raises(RuntimeError, match="cannot bind port"):
        await cli.serve(object())
    assert calls == ["stopped"]
