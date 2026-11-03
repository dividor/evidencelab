"""The ui container fills the api and mcp addresses into its nginx config.

``ui/frontend/nginx.conf`` used to hardcode ``api:8000``, ``mcp:8001`` and
Docker's DNS server, which only exist under Docker Compose. Cloud container
platforms give the services other addresses and put a load balancer in front
of nginx, so ``render-nginx-conf.sh`` fills these in at container start from
``API_UPSTREAM``, ``MCP_UPSTREAM``, ``NGINX_RESOLVER`` and
``NGINX_REAL_IP_FROM``, defaulting to the compose values. These tests run the
real script on the real template.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "ui" / "frontend" / "render-nginx-conf.sh"
TEMPLATE = REPO_ROOT / "ui" / "frontend" / "nginx.conf"
SETTINGS = ("API_UPSTREAM", "MCP_UPSTREAM", "NGINX_RESOLVER", "NGINX_REAL_IP_FROM")

pytestmark = pytest.mark.unit


def _render(tmp_path, template=TEMPLATE, args=None, **settings):
    env = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    env.update(settings)
    output = tmp_path / "default.conf"
    argv = [str(template), str(output)] if args is None else args
    result = subprocess.run(
        ["sh", str(SCRIPT), *argv],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output


class TestRenderNginxConf:
    def test_template_when_read_then_has_placeholders_not_compose_addresses(self):
        text = TEMPLATE.read_text()
        assert "api:8000" not in text
        assert "mcp:8001" not in text
        assert "127.0.0.11" not in text
        assert "set $api_upstream __API_UPSTREAM__;" in text
        assert text.count("proxy_pass $api_upstream;") == 2
        assert "set $mcp_upstream __MCP_UPSTREAM__;" in text
        assert "resolver __NGINX_RESOLVER__ valid=10s;" in text
        assert "set_real_ip_from __NGINX_REAL_IP_FROM__;" in text

    def test_render_when_no_settings_then_uses_compose_service_names(self, tmp_path):
        result, output = _render(tmp_path)

        assert result.returncode == 0, result.stderr
        text = output.read_text()
        assert "set $api_upstream http://api:8000;" in text
        assert "set $mcp_upstream http://mcp:8001;" in text
        assert "resolver 127.0.0.11 valid=10s;" in text
        assert "set_real_ip_from 127.0.0.1;" in text
        assert "__" not in text.replace("__NAME__", "")

    def test_render_when_settings_given_then_fills_them_in(self, tmp_path):
        result, output = _render(
            tmp_path,
            API_UPSTREAM="http://api.evidencelab.internal:8000",
            MCP_UPSTREAM="http://mcp.evidencelab.internal:8001",
            NGINX_RESOLVER="169.254.169.253",
            NGINX_REAL_IP_FROM="10.0.0.0/16",
        )

        assert result.returncode == 0, result.stderr
        text = output.read_text()
        assert "set $api_upstream http://api.evidencelab.internal:8000;" in text
        assert "set $mcp_upstream http://mcp.evidencelab.internal:8001;" in text
        assert "resolver 169.254.169.253 valid=10s;" in text
        assert "set_real_ip_from 10.0.0.0/16;" in text
        assert "api:8000" not in text

    @pytest.mark.parametrize(
        "value",
        ["http://api:8000;evil", "http://api|x", "http://a&b", "http://a b", "a\\b"],
    )
    def test_render_when_value_unsafe_then_fails_without_writing(self, tmp_path, value):
        result, output = _render(tmp_path, API_UPSTREAM=value)

        assert result.returncode == 1
        assert "invalid API_UPSTREAM" in result.stderr
        assert not output.exists()

    def test_render_when_template_has_no_placeholders_then_copies_it(self, tmp_path):
        custom = tmp_path / "custom.conf"
        custom.write_text("server { listen 80; }\n")

        result, output = _render(tmp_path, template=custom)

        assert result.returncode == 0, result.stderr
        assert output.read_text() == "server { listen 80; }\n"

    def test_render_when_arguments_missing_then_exits_with_usage(self, tmp_path):
        result, _ = _render(tmp_path, args=[str(TEMPLATE)])

        assert result.returncode == 2
        assert "usage:" in result.stderr
