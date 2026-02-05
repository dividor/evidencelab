#!/bin/sh
# Docker entrypoint script for UI container
# Injects API_SECRET_KEY into nginx config at runtime

# Replace environment variable in nginx config
envsubst '${API_SECRET_KEY}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
