#!/usr/bin/env bash
# Build the web app image with this deployment's settings and push it to the
# deployment's ECR repository.
#
# Usage: deploy/aws/scripts/build-ui-image.sh
#
# Run after the first `terraform apply` in deploy/aws. The build fixes the
# sign-in mode and the data sources from config.json into the page, so it
# uses the same config.json and sign-in mode as the deployment, read from the
# Terraform outputs. With anonymous_access, the page also carries the API key
# (read from Secrets Manager), so visitors can use the site without signing
# in, and anyone can read that key from the page.
#
# Needs docker (with buildx), the aws CLI and terraform. Set TERRAFORM to run
# terraform some other way, and AWS_PROFILE to pick the AWS account. CUSTOMIZE_ASSETS points at branding assets (default: customize/).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
tf="${TERRAFORM:-terraform}"

output() { $tf -chdir="$here" output -raw "$1"; }

repo_url="$(output ui_repository_url)"
tag="$(output ui_image_tag)"
region="$(output region)"
user_module="$(output user_module)"
site_url="$(output site_url)"
config_path="$(output config_json_path)"
anonymous_access="$(output anonymous_access)"

api_key=""
if [ "$anonymous_access" = true ]; then
    api_key="$(aws secretsmanager get-secret-value --region "$region" \
        --secret-id "$(output app_secret_id)" --query SecretString --output text |
        python3 -c 'import json, sys; print(json.load(sys.stdin)["API_SECRET_KEY"])')"
fi

# The Dockerfile reads config.json from a build context of its own.
config_dir="$(mktemp -d)"
trap 'rm -rf "$config_dir"' EXIT
(cd "$here" && cp "$config_path" "$config_dir/config.json")

registry="${repo_url%%/*}"

echo "Building $repo_url:$tag (sign-in mode $user_module, anonymous access $anonymous_access, site $site_url)"
docker buildx build \
    --platform linux/arm64 \
    --file "$repo_root/ui/frontend/Dockerfile.prod" \
    --build-context config="$config_dir" \
    --build-context customize="${CUSTOMIZE_ASSETS:-$repo_root/customize}" \
    --build-arg REACT_APP_API_BASE_URL=/api \
    --build-arg REACT_APP_USER_MODULE="$user_module" \
    --build-arg REACT_APP_API_KEY="$api_key" \
    --build-arg REACT_APP_SITE_URL="$site_url" \
    --tag "$repo_url:$tag" \
    --load \
    "$repo_root"

# Push separately from the build, signing in again before each attempt: a
# long build can outlast the registry session, and a push can drop mid-way.
for attempt in 1 2 3; do
    aws ecr get-login-password --region "$region" |
        docker login --username AWS --password-stdin "$registry" >/dev/null
    if docker push "$repo_url:$tag"; then
        echo "Pushed $repo_url:$tag"
        exit 0
    fi
    echo "Push attempt $attempt failed." >&2
    sleep 10
done
echo "Could not push $repo_url:$tag after 3 attempts." >&2
exit 1
