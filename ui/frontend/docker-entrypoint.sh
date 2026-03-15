#!/bin/sh
# Docker entrypoint script for UI container
# Injects API_SECRET_KEY into nginx config at runtime

# Replace environment variable in nginx config
envsubst '${API_SECRET_KEY}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# Generate Microsoft identity association file if client ID is configured
if [ -n "$OAUTH_MICROSOFT_CLIENT_ID" ]; then
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
    echo "Generated .well-known/microsoft-identity-association.json"
fi

# Start nginx
exec nginx -g 'daemon off;'
