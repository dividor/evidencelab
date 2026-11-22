"""A signed-out browser can read the sign-in options on a site that requires sign-in.

The sign-in screen asks /config/auth-status which ways to sign in are on before
anyone is signed in. On a site that requires sign-in (USER_MODULE=on_active)
the web app carries no key, so the request has neither a key nor a session and
must pass every gate the real API app puts in front of it. Each gate has its
own list of open paths, and once only one of them listed this path, so the
sign-in screen fell back to an email form.

The real app reads USER_MODULE when it is imported, so it is started in a
subprocess with the settings of such a site: email login off, Microsoft only.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

PROBE = """
import json
from fastapi.testclient import TestClient
import ui.backend.main as main

client = TestClient(main.app)
status = client.get("/config/auth-status")
data_sources = client.get("/config/datasources")
print(json.dumps({
    "middleware": [m.cls.__name__ for m in main.app.user_middleware],
    "auth_status": status.status_code,
    "auth_status_body": status.json(),
    "data_sources": data_sources.status_code,
}))
"""


@pytest.fixture(scope="module")
def signed_out():
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(("OAUTH_", "REACT_APP_")):
            del env[name]
    # Set, not just removed: the app loads a .env file, which fills in any
    # variable that is missing but never replaces one that is set.
    env.update(
        {
            "OAUTH_GOOGLE_CLIENT_ID": "",
            "OAUTH_GOOGLE_CLIENT_SECRET": "",
            "REACT_APP_API_KEY": "",
            "USER_MODULE": "on_active",
            "DISABLE_EMAIL_LOGIN": "true",
            "AUTH_SECRET_KEY": secrets.token_hex(32),
            "API_SECRET_KEY": secrets.token_hex(16),
            "OAUTH_MICROSOFT_CLIENT_ID": "test-client-id",
            "OAUTH_MICROSOFT_CLIENT_SECRET": secrets.token_hex(8),
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_auth_status_when_signed_out_on_active_site_then_answers(signed_out):
    assert "ActiveAuthMiddleware" in signed_out["middleware"]
    assert signed_out["auth_status"] == 200
    body = signed_out["auth_status_body"]
    assert body["user_module_mode"] == "on_active"
    assert body["email_login_disabled"] is True
    assert body["microsoft_oauth_enabled"] is True
    assert body["google_oauth_enabled"] is False


def test_data_when_signed_out_on_active_site_then_refused(signed_out):
    assert signed_out["data_sources"] == 401
