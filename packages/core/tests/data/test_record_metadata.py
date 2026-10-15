from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from cubos.data import record_metadata


def test_nested_secrets_opaque_objects_and_nonfinite_are_safe():
    class Opaque:
        def __repr__(self):
            raise AssertionError("opaque repr must not be called")

    result = record_metadata.sanitize({
        "api_key": "secret", "nested": [{"password": "secret", "safe": 3}],
        "opaque": Opaque(), "values": [float("nan"), float("inf"), -float("inf")],
        "url": "https://user:password@example.org/read?token=secret&limit=2",
    })
    assert result["api_key"] == "[redacted]"
    assert result["nested"] == [{"password": "[redacted]", "safe": 3}]
    assert result["opaque"] == "[omitted object]"
    assert result["values"] == [None, None, None]
    parsed = urlsplit(result["url"])
    assert parsed.netloc == "example.org"
    assert parse_qs(parsed.query) == {"token": ["[redacted]"], "limit": ["2"]}


def test_nested_urls_and_fragments_cannot_leak_credentials():
    result = record_metadata.sanitize(
        "https://example.org/?next=https%3A%2F%2Fuser%3Apassword%40other.org%2F%3Ftoken%3Dsecret#access_token=fragment-secret")
    assert "password" not in result
    assert "fragment-secret" not in result
    nested = parse_qs(urlsplit(result).query)["next"][0]
    assert "secret" not in nested


def test_dataclass_metadata_does_not_deepcopy_opaque_objects():
    class Opaque:
        def __deepcopy__(self, memo):
            raise AssertionError("do not deepcopy metadata objects")

    @dataclass
    class Metadata:
        value: object

    Metadata.__module__ = "cubos.test"
    assert record_metadata.sanitize(Metadata(Opaque())) == {"value": "[omitted object]"}


def test_software_identity_tracks_installed_version_and_checkout(monkeypatch):
    monkeypatch.setattr(record_metadata, "version", lambda package: "1.2.3")
    def output(args, **kwargs):
        return "abcdef123\n" if "rev-parse" in args else " M changed.py\n"
    monkeypatch.setattr(record_metadata.subprocess, "check_output", output)
    assert record_metadata.software_identity() == {
        "cubos_version": "1.2.3", "commit": "abcdef123", "dirty": True}
