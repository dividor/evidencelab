"""Unit tests for the evaluation-harness router wiring.

Verifies (without spinning up auth) that every endpoint is gated to superusers
and that the expected CRUD + experiment routes exist — i.e. the harness is
admin-only, never user-facing.
"""

import pytest

import ui.backend.routes.testing as testing
from ui.backend.auth.users import current_superuser

pytestmark = pytest.mark.unit


def _api_routes():
    return [r for r in testing.router.routes if hasattr(r, "dependant")]


def _dependency_calls(route):
    return [dep.call for dep in route.dependant.dependencies]


def test_every_endpoint_requires_superuser():
    routes = _api_routes()
    assert routes, "router exposes no API routes"
    for route in routes:
        assert current_superuser in _dependency_calls(
            route
        ), f"{list(route.methods)} {route.path} is missing the superuser gate"


def test_expected_routes_are_registered():
    registered = {route.path for route in _api_routes()}
    expected_paths = {
        "/datasets",
        "/datasets/{dataset_id}",
        "/datasets/{dataset_id}/cases",
        "/cases/{case_id}",
        "/experiments",
        "/experiments/{experiment_id}",
        "/experiments/{experiment_id}/run",
        "/experiments/{experiment_id}/cancel",
    }
    for path in expected_paths:
        assert path in registered, f"missing route {path}"
