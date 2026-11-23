#!/bin/sh
# Render the nginx config template for the ui container.
#
# Usage: render-nginx-conf.sh TEMPLATE OUTPUT
#
# Fills in the placeholders in TEMPLATE and writes OUTPUT:
#   __API_UPSTREAM__    API_UPSTREAM    default http://api:8000
#   __MCP_UPSTREAM__    MCP_UPSTREAM    default http://mcp:8001
#   __NGINX_RESOLVER__  NGINX_RESOLVER  default 127.0.0.11 (Docker's DNS server)
#   __NGINX_REAL_IP_FROM__  NGINX_REAL_IP_FROM  default 127.0.0.1 (no proxy in
#                       front of nginx is trusted to report the visitor's address)
#   __UI_CSP_POLICY__   UI_CSP_POLICY   default below: the Content-Security-Policy
#                       on every page and file nginx serves (security-headers.conf)
#
# The defaults match Docker Compose, so compose deployments need no settings.
# Cloud container platforms, where the services have other addresses, Docker's
# DNS server does not exist and a load balancer sits in front of nginx, set
# all four.
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: render-nginx-conf.sh TEMPLATE OUTPUT" >&2
    exit 2
fi
template="$1"
output="$2"

API_UPSTREAM="${API_UPSTREAM:-http://api:8000}"
MCP_UPSTREAM="${MCP_UPSTREAM:-http://mcp:8001}"
NGINX_RESOLVER="${NGINX_RESOLVER:-127.0.0.11}"
NGINX_REAL_IP_FROM="${NGINX_REAL_IP_FROM:-127.0.0.1}"

# Scripts and workers from this site only (the PDF viewer's PDF.js included),
# plus Google Analytics, which the app loads only after cookie consent. Styles
# allow inline: React and the MCP consent page set style attributes. Images
# allow any https address (document thumbnails and figures from data sources).
# form-action is left out on purpose: it does not fall back to default-src, and
# the MCP consent form's answer redirects to the MCP client's own address.
# A deployment that loads other outside assets sets UI_CSP_POLICY to extend it.
DEFAULT_UI_CSP_POLICY="default-src 'self'; script-src 'self' https://*.googletagmanager.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com; worker-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
UI_CSP_POLICY="${UI_CSP_POLICY:-$DEFAULT_UI_CSP_POLICY}"

# The values are written into the config with sed, so refuse anything that is
# empty or could break the substitution or the nginx directive.
check_value() {
    if [ -z "$2" ] || printf '%s' "$2" | grep -q '[|&;\\[:space:]]'; then
        echo "render-nginx-conf: invalid $1: '$2'" >&2
        exit 1
    fi
}
check_value API_UPSTREAM "$API_UPSTREAM"
check_value MCP_UPSTREAM "$MCP_UPSTREAM"
check_value NGINX_RESOLVER "$NGINX_RESOLVER"
check_value NGINX_REAL_IP_FROM "$NGINX_REAL_IP_FROM"

# The policy has spaces, semicolons and quotes, so it gets its own check: refuse
# what would break the sed substitution (| & \\), the quoted nginx string ("),
# or be read by nginx as a variable ($), and line breaks.
check_policy() {
    if printf '%s' "$2" | grep -q '[|&\\"$]' || [ "$(printf '%s' "$2" | wc -l)" -ne 0 ] \
        || printf '%s' "$2" | grep -q "$(printf '\r')"; then
        echo "render-nginx-conf: invalid $1: it must be one line without | & \\ \" or \$" >&2
        exit 1
    fi
}
check_policy UI_CSP_POLICY "$UI_CSP_POLICY"

sed \
    -e "s|__API_UPSTREAM__|${API_UPSTREAM}|g" \
    -e "s|__MCP_UPSTREAM__|${MCP_UPSTREAM}|g" \
    -e "s|__NGINX_RESOLVER__|${NGINX_RESOLVER}|g" \
    -e "s|__NGINX_REAL_IP_FROM__|${NGINX_REAL_IP_FROM}|g" \
    -e "s|__UI_CSP_POLICY__|${UI_CSP_POLICY}|g" \
    "$template" > "$output"

if grep -qE '__(API_UPSTREAM|MCP_UPSTREAM|NGINX_RESOLVER|NGINX_REAL_IP_FROM|UI_CSP_POLICY)__' "$output"; then
    echo "render-nginx-conf: unfilled placeholder left in $output" >&2
    exit 1
fi
