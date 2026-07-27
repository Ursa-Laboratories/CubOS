from io import BytesIO

from cubos_api.desktop import _watch_for_shutdown


class _Server:
    should_exit = False


def test_desktop_backend_stops_when_parent_stdin_closes() -> None:
    server = _Server()

    _watch_for_shutdown(server, BytesIO(b""))

    assert server.should_exit is True
