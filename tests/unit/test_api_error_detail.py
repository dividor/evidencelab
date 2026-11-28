"""Errors on the server stay in the server log; the client gets a fixed message.

23 API routes caught every exception and sent its text to the client
(``HTTPException(500, detail=str(e))``), which went around the app's own
sanitising handler. On an AWS deployment the browser received "connection
pool exhausted"; other errors can carry SQL, file paths or host names. The
routes now raise ``server_error(e, ...)``: a request that waited too long for
a database connection gets 503 "busy", anything else 500 with a fixed message.
"""

import ast
import asyncio
import importlib
import logging
import os
import pathlib
from typing import List
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import ui.backend.utils.errors as errors
from pipeline.db.postgres_client_base import PostgresPoolTimeout
from ui.backend.routes import documents as documents_routes

pytestmark = pytest.mark.unit

DOC_ID = "11111111-1111-5111-8111-111111111111"
INTERNAL_TEXT = "could not connect to server at /var/run/postgresql/.s.PGSQL.5432"
REPO = pathlib.Path(__file__).resolve().parents[2]


class TestServerError:
    def test_server_error_when_pool_timeout_then_503_busy(self, caplog):
        exc = PostgresPoolTimeout("no Postgres connection came free within 30s")
        with caplog.at_level(logging.WARNING):
            http = errors.server_error(exc, "Facets error", logging.getLogger("t"))
        assert http.status_code == 503
        assert http.detail == errors.BUSY_DETAIL
        assert "came free" in caplog.text, "the reason stays in the server log"

    def test_server_error_when_other_error_then_500_without_its_text(
        self, caplog, monkeypatch
    ):
        monkeypatch.setattr(errors, "API_DEBUG", False)
        with caplog.at_level(logging.ERROR):
            try:
                raise RuntimeError(INTERNAL_TEXT)
            except RuntimeError as exc:
                http = errors.server_error(exc, "Search error", logging.getLogger("t"))
        assert http.status_code == 500
        assert http.detail == errors.INTERNAL_ERROR_DETAIL
        assert INTERNAL_TEXT not in str(http.detail)
        record = caplog.records[-1]
        assert INTERNAL_TEXT in record.getMessage()
        assert record.exc_info, "the traceback goes to the log"

    def test_server_error_when_api_debug_then_shows_text(self, monkeypatch):
        monkeypatch.setattr(errors, "API_DEBUG", True)
        http = errors.server_error(
            RuntimeError(INTERNAL_TEXT), "x", logging.getLogger("t")
        )
        assert http.detail == INTERNAL_TEXT


class TestValueErrorDetail:
    def test_value_error_detail_when_safe_prefix_then_shown(self, monkeypatch):
        monkeypatch.setattr(errors, "API_DEBUG", False)
        msg = "Invalid data_source: foo"
        assert errors.value_error_detail(ValueError(msg)) == msg

    def test_value_error_detail_when_other_then_generic(self, monkeypatch):
        monkeypatch.setattr(errors, "API_DEBUG", False)
        detail = errors.value_error_detail(ValueError("column sys_x does not exist"))
        assert detail == errors.INVALID_REQUEST_DETAIL


class _FailingPg:
    def __init__(self, exc: Exception):
        self.exc = exc

    def fetch_docs(self, doc_ids):
        raise self.exc


def _thumbnail(monkeypatch, exc: Exception):
    monkeypatch.setattr(errors, "API_DEBUG", False)
    monkeypatch.setattr(
        documents_routes, "get_pg_for_source", lambda _s=None: _FailingPg(exc)
    )
    app = FastAPI()
    app.include_router(documents_routes.router)
    with TestClient(app) as client:
        return client.get(
            f"/document/{DOC_ID}/thumbnail", params={"data_source": "uneg"}
        )


class TestThumbnailRoute:
    def test_thumbnail_when_no_connection_comes_free_then_503(self, monkeypatch):
        response = _thumbnail(
            monkeypatch, PostgresPoolTimeout("no Postgres connection came free")
        )
        assert response.status_code == 503
        assert response.json() == {"detail": errors.BUSY_DETAIL}

    def test_thumbnail_when_database_fails_then_500_without_its_text(self, monkeypatch):
        response = _thumbnail(monkeypatch, RuntimeError(INTERNAL_TEXT))
        assert response.status_code == 500
        assert response.json() == {"detail": errors.INTERNAL_ERROR_DETAIL}


class TestAppHandler:
    def test_app_when_pool_timeout_escapes_a_route_then_503(self):
        """Routes without their own handler still answer 503, not 500."""
        env = dict(os.environ, API_SECRET_KEY="")
        with patch.dict(os.environ, env, clear=True):
            import ui.backend.main as main_module

            main_module = importlib.reload(main_module)
        request = Request(
            {"type": "http", "method": "GET", "path": "/x", "headers": []}
        )
        response = asyncio.run(
            main_module.postgres_pool_timeout_handler(
                request, PostgresPoolTimeout("no Postgres connection came free")
            )
        )
        assert response.status_code == 503
        assert errors.BUSY_DETAIL.encode() in response.body


# --- Guard: no route sends a caught error's text to the client ---------------

_BROAD = {"Exception", "BaseException"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(t, ast.Name) and t.id in _BROAD for t in types)


def _leaks(source: str) -> List[int]:
    """Lines where a broad ``except ... as e`` sends ``e``'s text as a detail."""
    found = []
    for handler in ast.walk(ast.parse(source)):
        if not (
            isinstance(handler, ast.ExceptHandler)
            and handler.name
            and _is_broad(handler)
        ):
            continue
        for node in (n for stmt in handler.body for n in ast.walk(stmt)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "HTTPException":
                continue
            details = [k.value for k in node.keywords if k.arg == "detail"]
            details += node.args[1:2]
            for detail in details:
                if any(
                    isinstance(n, ast.Name) and n.id == handler.name
                    for n in ast.walk(detail)
                ):
                    found.append(node.lineno)
    return found


class TestNoRouteSendsCaughtErrorText:
    def test_api_when_scanned_then_no_broad_handler_sends_error_text(self):
        leaks = []
        for path in sorted((REPO / "ui" / "backend").rglob("*.py")):
            for line in _leaks(path.read_text()):
                leaks.append(f"{path.relative_to(REPO)}:{line}")
        assert leaks == [], (
            "These handlers catch every exception and send its text to the "
            "client, which can expose SQL, file paths or host names. Raise "
            "server_error(e, ...) from ui.backend.utils.errors instead: "
            + ", ".join(leaks)
        )

    def test_guard_when_a_handler_leaks_then_it_is_found(self):
        """Self-check: the guard above can fail."""
        sample = (
            "def a():\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as e:\n"
            "        raise HTTPException(status_code=500, detail=str(e))\n"
            "def b():\n"
            "    try:\n"
            "        pass\n"
            "    except (KeyError, Exception) as err:\n"
            "        raise HTTPException(500, f'failed: {err}')\n"
            "def c():\n"
            "    try:\n"
            "        pass\n"
            "    except KeyError as e:\n"
            "        raise HTTPException(status_code=404, detail=str(e))\n"
        )
        assert _leaks(sample) == [5, 10]
