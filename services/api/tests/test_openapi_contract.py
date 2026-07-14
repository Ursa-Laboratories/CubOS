"""Release guard for the versioned CubOS appliance API surface."""

from cubos_api.app import create_app


def test_openapi_contains_versioned_discovery_and_run_resources():
    schema = create_app().openapi()
    paths = schema["paths"]

    expected = {
        "/api/v1/health": {"get"},
        "/api/v1/version": {"get"},
        "/api/v1/capabilities": {"get"},
        "/api/v1/runs": {"post"},
        "/api/v1/runs/{run_id}": {"get"},
        "/api/v1/runs/{run_id}/cancel": {"post"},
        "/api/v1/runs/{run_id}/events": {"get"},
        "/api/v1/runs/{run_id}/artifacts": {"get"},
        "/api/v1/runs/{run_id}/artifacts/{name}": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= set(paths[path])

    assert "202" in paths["/api/v1/runs"]["post"]["responses"]
    assert "202" in paths["/api/v1/runs/{run_id}/cancel"]["post"]["responses"]
