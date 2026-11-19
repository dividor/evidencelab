"""Document write and pipeline routes are for signed-in administrators only.

The API key alone must not reach them: with sign-in off or on_passive that
key is built into the browser bundle, so anyone could otherwise delete a
document's chunks or edit its metadata.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ui.backend.auth.optional_user import resolve_optional_user
from ui.backend.routes import documents as documents_routes

ADMIN_ROUTES = {
    ("GET", "/document/{doc_id}/logs"),
    ("PUT", "/document/{doc_id}/toc"),
    ("PATCH", "/documents/{doc_id}"),
    ("POST", "/documents/{doc_id}/reprocess-toc"),
    ("GET", "/queue/status"),
    ("POST", "/documents/{doc_id}/reprocess"),
}

ADMIN = SimpleNamespace(id="admin-1", is_superuser=True)
MEMBER = SimpleNamespace(id="user-1", is_superuser=False)


def _route_dependencies(path: str, method: str) -> list:
    for route in documents_routes.router.routes:
        if getattr(route, "path", None) == path and method in route.methods:
            return [d.call for d in route.dependant.dependencies]
    raise AssertionError(f"route {method} {path} not found")


def _client(user) -> TestClient:
    app = FastAPI()
    app.include_router(documents_routes.router)

    async def _user():
        return user

    app.dependency_overrides[resolve_optional_user] = _user
    return TestClient(app)


@pytest.mark.asyncio
async def test_require_document_admin_when_signed_out_then_401():
    with pytest.raises(HTTPException) as exc:
        await documents_routes.require_document_admin(None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_document_admin_when_not_superuser_then_403():
    with pytest.raises(HTTPException) as exc:
        await documents_routes.require_document_admin(MEMBER)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_document_admin_when_superuser_then_returns_user():
    assert await documents_routes.require_document_admin(ADMIN) is ADMIN


@pytest.mark.parametrize("method,path", sorted(ADMIN_ROUTES))
def test_admin_routes_when_registered_then_require_document_admin(method, path):
    assert documents_routes.require_document_admin in _route_dependencies(path, method)


@pytest.mark.parametrize(
    "method,url",
    [
        ("POST", "/documents/doc-1/reprocess"),
        ("PUT", "/document/doc-1/toc"),
        ("PATCH", "/documents/doc-1"),
        ("POST", "/documents/doc-1/reprocess-toc"),
        ("GET", "/queue/status"),
        ("GET", "/document/doc-1/logs"),
    ],
)
@pytest.mark.parametrize("user,expected", [(None, 401), (MEMBER, 403)])
def test_admin_routes_when_not_admin_then_refused_before_touching_data(
    monkeypatch, method, url, user, expected
):
    def _fail(*_args, **_kwargs):
        raise AssertionError("the route body ran for a caller who is not an admin")

    monkeypatch.setattr(documents_routes, "get_db_for_source", _fail)
    monkeypatch.setattr(documents_routes, "get_pg_for_source", _fail)
    body = {"toc_classified": "x"} if url.endswith("/toc") else {}
    response = _client(user).request(method, url, json=body)
    assert response.status_code == expected


def test_reprocess_when_admin_then_route_runs(monkeypatch):
    calls = []
    db = SimpleNamespace(
        get_document=lambda doc_id: {"id": doc_id, "filepath": "a.pdf"},
        delete_document_chunks=lambda doc_id: calls.append(("delete", doc_id)),
        update_document=lambda doc_id, fields: calls.append(("update", doc_id)),
    )
    monkeypatch.setattr(documents_routes, "get_db_for_source", lambda _: db)
    task_module = SimpleNamespace(
        reprocess_document=SimpleNamespace(delay=lambda *a: SimpleNamespace(id="t-1"))
    )
    monkeypatch.setitem(
        documents_routes.sys.modules, "pipeline.utilities.tasks", task_module
    )

    response = _client(ADMIN).post("/documents/doc-1/reprocess?data_source=uneg")

    assert response.status_code == 200
    assert response.json()["task_id"] == "t-1"
    assert ("delete", "doc-1") in calls


@pytest.mark.asyncio
async def test_reprocess_toc_when_data_source_unknown_then_rejected():
    with pytest.raises(ValueError, match="Invalid data_source"):
        await documents_routes.reprocess_document_toc(
            "doc-1", data_source="not-a-source"
        )


def test_public_document_routes_when_registered_then_not_admin_only():
    """Reading routes stay available to ordinary callers."""
    public = {
        ("GET", "/documents"),
        ("GET", "/document/{doc_id}"),
        ("GET", "/documents/{doc_id}/chunks"),
        ("GET", "/pdf/{doc_id}"),
    }
    for method, path in public:
        deps = _route_dependencies(path, method)
        assert documents_routes.require_document_admin not in deps
