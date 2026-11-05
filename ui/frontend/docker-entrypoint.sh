#!/bin/sh
# Docker entrypoint script for UI container

# Render the nginx config: fill in the api and mcp addresses and the DNS
# resolver. Stop here if that fails, rather than start with a broken config.
/render-nginx-conf.sh /etc/nginx/conf.d/default.conf.template /etc/nginx/conf.d/default.conf || exit 1

# Generate Microsoft identity association file for publisher verification.
# Only needed for multi-tenant apps (common/organizations) where users from
# other orgs see the "unverified" warning. Single-tenant deployments should
# NOT expose the app ID publicly.
if [ -n "$OAUTH_MICROSOFT_CLIENT_ID" ]; then
    case "${OAUTH_MICROSOFT_TENANT_ID:-}" in
        common|organizations)
            mkdir -p /usr/share/nginx/html/.well-known
            cat > /usr/share/nginx/html/.well-known/microsoft-identity-association.json <<MSEOF
{
  "associatedApplications": [
    {
      "applicationId": "${OAUTH_MICROSOFT_CLIENT_ID}"
    }
  ]
}
MSEOF
            echo "Generated .well-known/microsoft-identity-association.json (multi-tenant)"
            ;;
        *)
            echo "Skipping .well-known/microsoft-identity-association.json (single-tenant)"
            ;;
    esac
fi

# Start nginx
exec nginx -g 'daemon off;'
