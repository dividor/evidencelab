#!/usr/bin/env bash
# Build the web app image with this deployment's settings and push it to the
# deployment's Azure Container Registry.
#
# Usage: deploy/azure/scripts/build-ui-image.sh TAG
#
# Run after the first `terraform apply` in deploy/azure. The build fixes the
# sign-in mode and the data sources from config.json into the page, so it
# uses the same config.json and sign-in mode as the deployment, read from the
# Terraform outputs. With anonymous_access, the page also carries the API key,
# so visitors can use the site without signing in, and anyone can read that
# key from the page.
#
# Container Apps runs amd64 images. On an Apple silicon (arm64) computer
# Docker builds through emulation, which is slower.
#
# Needs docker (with buildx), the az CLI and terraform. Set TERRAFORM to run
# terraform some other way. CUSTOMIZE_ASSETS points at branding assets
# (default: customize/).
set -euo pipefail

tag="${1:?usage: build-ui-image.sh TAG}"
here="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
tf="${TERRAFORM:-terraform}"

output() { $tf -chdir="$here" output -raw "$1"; }

subscription="$(output subscription_id)"
registry="$(output registry)"
login_server="$(output registry_login_server)"
user_module="$(output user_module)"
site_url="$(output site_url)"
config_path="$(output config_json_path)"
anonymous_access="$(output anonymous_access)"

api_key=""
if [ "$anonymous_access" = true ]; then
    api_key="$(output api_secret_key)"
fi

# The Dockerfile reads config.json from a build context of its own.
config_dir="$(mktemp -d)"
trap 'rm -rf "$config_dir"' EXIT
(cd "$here" && cp "$config_path" "$config_dir/config.json")

image="$login_server/ui:$tag"
echo "Building $image (sign-in mode $user_module, anonymous access $anonymous_access, site $site_url)"
docker buildx build \
    --platform linux/amd64 \
    --file "$repo_root/ui/frontend/Dockerfile.prod" \
    --build-context config="$config_dir" \
    --build-context customize="${CUSTOMIZE_ASSETS:-$repo_root/customize}" \
    --build-arg REACT_APP_API_BASE_URL=/api \
    --build-arg REACT_APP_USER_MODULE="$user_module" \
    --build-arg REACT_APP_API_KEY="$api_key" \
    --build-arg REACT_APP_SITE_URL="$site_url" \
    --tag "$image" \
    --load \
    "$repo_root"

# Push separately from the build, signing in again before each attempt: a
# long build can outlast the registry session, and a push can drop mid-way.
for attempt in 1 2 3; do
    az acr login --subscription "$subscription" --name "$registry" >/dev/null
    if docker push "$image"; then
        echo "Pushed $image"
        exit 0
    fi
    echo "Push attempt $attempt failed." >&2
    sleep 10
done
echo "Could not push $image after 3 attempts." >&2
exit 1
