"""Every page and file nginx serves carries the security headers.

nginx drops all server-level ``add_header`` lines for a location that sets
any ``add_header`` of its own. That is how the SPA pages and static files
were served with no security headers at all, so the headers live in one
snippet that each such location must include.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "ui" / "frontend" / "nginx.conf"
SNIPPET = REPO_ROOT / "ui" / "frontend" / "nginx-security-headers.conf"
DOCKERFILE = REPO_ROOT / "ui" / "frontend" / "Dockerfile.prod"
ENTRYPOINT = REPO_ROOT / "ui" / "frontend" / "docker-entrypoint.sh"
INCLUDE_LINE = "include /etc/nginx/snippets/security-headers.conf;"

REQUIRED_HEADERS = (
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Strict-Transport-Security",
    "Content-Security-Policy",
)


def _location_blocks(conf: str) -> list[tuple[str, str]]:
    """Return (header line, body) for each top-level location block."""
    blocks = []
    for match in re.finditer(r"^\s*location\b[^{]*\{", conf, flags=re.MULTILINE):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(conf[i], 0)
            i += 1
        blocks.append((match.group(0).strip(), conf[match.end() : i - 1]))
    return blocks


def test_snippet_when_read_then_sets_every_required_header_always():
    snippet = SNIPPET.read_text()
    for header in REQUIRED_HEADERS:
        assert re.search(
            rf'add_header {header} ".+" always;', snippet
        ), f"{header} missing from {SNIPPET.name}"


def test_nginx_conf_when_read_then_includes_snippet_at_server_level():
    conf = NGINX_CONF.read_text()
    server_level = re.split(r"^\s*location\b", conf, maxsplit=1, flags=re.MULTILINE)[0]
    assert INCLUDE_LINE in server_level


def test_locations_with_own_add_header_when_read_then_include_snippet():
    for header, body in _location_blocks(NGINX_CONF.read_text()):
        if "add_header" in body:
            assert (
                INCLUDE_LINE in body
            ), f"{header} sets add_header but drops the security headers"


def test_nginx_conf_when_read_then_no_security_header_set_outside_snippet():
    conf = NGINX_CONF.read_text()
    for header in REQUIRED_HEADERS:
        assert f"add_header {header}" not in conf, f"{header} belongs in the snippet"


def test_dockerfile_when_read_then_renders_snippet_where_conf_includes_it():
    # The snippet is a template (its Content-Security-Policy comes from
    # UI_CSP_POLICY), so the image holds the template and the entrypoint
    # writes the file that nginx.conf includes before nginx starts.
    assert (
        "COPY ui/frontend/nginx-security-headers.conf "
        "/etc/nginx/snippets/security-headers.conf.template\n" in DOCKERFILE.read_text()
    )
    assert (
        "/render-nginx-conf.sh /etc/nginx/snippets/security-headers.conf.template "
        "/etc/nginx/snippets/security-headers.conf || exit 1" in ENTRYPOINT.read_text()
    )


def test_dockerfile_when_read_then_builds_without_inline_script():
    # script-src 'self' would block Create React App's inline runtime script.
    build = DOCKERFILE.read_text().split("RUN npm run build", 1)[0]
    assert "ENV INLINE_RUNTIME_CHUNK=false" in build
