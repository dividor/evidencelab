#!/usr/bin/env bash
# Redeploy Evidence Lab (production) from a release branch.
#
# This script is intended to be invoked by the GitHub Actions self-hosted
# runner on the deployment VM after a merge into the current release
# branch (``rc/v*``). It performs the full release dance:
#
#   1. Refreshes the deployment sub-repo so its canonical ``config.json``
#      and ``nginx.conf`` are at the right commit.
#   2. Copies those two files into the main repo working tree so the
#      Docker images get built with the correct config.
#   3. Hard-resets the main repo to ``origin/$BRANCH`` so the build sees
#      exactly what's on the release branch — no stray working-tree
#      edits, no half-applied merges.
#   4. Rebuilds + restarts the prod compose stack (``--build``, no cache
#      bust beyond what compose does naturally).
#   5. Probes ``/health`` until the api answers 200 (or fails the deploy
#      after a bounded retry budget).
#
# It is intentionally:
#   - idempotent  — re-running with no upstream changes is a no-op
#   - locked      — concurrent invocations are rejected via ``flock``
#   - destructive on the working tree — that's the whole point; any
#     uncommitted edit on the VM is wiped by ``git reset --hard``.
#
# Usage:
#     scripts/deploy/redeploy_prod.sh [BRANCH]
#
# BRANCH defaults to the value of ``$GITHUB_REF_NAME`` (set by the
# Actions runner) and falls back to ``rc/v1.5.0`` for manual invocations.
#
# Environment overrides:
#   DEPLOY_DIR       — repo root to deploy from (default: this script's
#                      grandparent dir, i.e. /home/.../projects/evidencelab)
#   SUBREPO_DIR      — deployment sub-repo path (operator-specific; the
#                      public default is a placeholder — set this via the
#                      EVIDENCELAB_SUBREPO_DIR repo variable in the
#                      workflow so prod points at the real directory)
#                      (default: $DEPLOY_DIR/pipeline/integration/client1)
#   HEALTH_URL       — health endpoint to probe
#                      (default: http://127.0.0.1:8000/health)
#   HEALTH_RETRIES   — max retries (default: 30, ~90s with 3s delay)
#   HEALTH_DELAY_S   — seconds between health probes (default: 3)
#   SKIP_HEALTH      — set to 1 to skip the post-deploy health check
#                      (escape hatch; the workflow never sets this)
set -euo pipefail

BRANCH="${1:-${GITHUB_REF_NAME:-rc/v1.5.0}}"

# Resolve repo root from the script's location so this works regardless of
# the runner's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SUBREPO_DIR="${SUBREPO_DIR:-$DEPLOY_DIR/pipeline/integration/client1}"
DEPLOY_DEPLOYMENT_DIR="$SUBREPO_DIR/evidencelab/deployment"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
HEALTH_DELAY_S="${HEALTH_DELAY_S:-3}"

LOCKFILE=/tmp/evidencelab-deploy.lock
COMPOSE_ARGS=(-f docker-compose.prod.yml -f docker-compose.prod.override.yml)

log() {
    # Banner-style log lines so deploy events stand out in journalctl / GH UI.
    printf '[deploy %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"
}

# ---------------------------------------------------------------------------
# Concurrency guard. The GH Actions ``concurrency`` block already serialises
# pushes, but a manual invocation racing with an Actions run would otherwise
# leave docker compose in an undefined state. ``flock`` makes the second one
# exit cleanly.
# ---------------------------------------------------------------------------
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    log "another deploy is already in progress (lock: $LOCKFILE) — aborting"
    exit 1
fi

log "===================================================================="
log "Evidence Lab — redeploy"
log "  branch       : $BRANCH"
log "  deploy dir   : $DEPLOY_DIR"
log "  sub-repo dir : $SUBREPO_DIR"
log "===================================================================="

cd "$DEPLOY_DIR"

# ---------------------------------------------------------------------------
# Step 1 — refresh the deployment sub-repo.
# ---------------------------------------------------------------------------
if [[ -d "$SUBREPO_DIR/.git" ]]; then
    log "refreshing deployment sub-repo"
    git -C "$SUBREPO_DIR" fetch --prune origin
    # Track whichever default branch the sub-repo uses; common pattern is main.
    SUBREPO_BRANCH="$(git -C "$SUBREPO_DIR" symbolic-ref --short HEAD 2>/dev/null || echo main)"
    git -C "$SUBREPO_DIR" reset --hard "origin/$SUBREPO_BRANCH"
else
    log "WARNING: sub-repo not present at $SUBREPO_DIR — config files will not be refreshed"
fi

# ---------------------------------------------------------------------------
# Step 2 — copy canonical config.json + nginx.conf into the main repo so
# the docker build picks them up. These files are .gitignored / not tracked
# in the main repo on purpose; their authoritative copies live in the
# sub-repo's ``evidencelab/deployment/`` dir.
# ---------------------------------------------------------------------------
if [[ -f "$DEPLOY_DEPLOYMENT_DIR/config.json" ]]; then
    log "copy config.json from sub-repo"
    cp "$DEPLOY_DEPLOYMENT_DIR/config.json" "$DEPLOY_DIR/config.json"
else
    log "WARNING: $DEPLOY_DEPLOYMENT_DIR/config.json missing — skipping copy"
fi
if [[ -f "$DEPLOY_DEPLOYMENT_DIR/nginx.conf" ]]; then
    log "copy nginx.conf from sub-repo"
    cp "$DEPLOY_DEPLOYMENT_DIR/nginx.conf" "$DEPLOY_DIR/nginx.conf"
else
    log "WARNING: $DEPLOY_DEPLOYMENT_DIR/nginx.conf missing — skipping copy"
fi

# ---------------------------------------------------------------------------
# Step 3 — fast-forward the main repo to the release branch tip.
# Hard-reset so the working tree matches origin exactly. config.json and
# nginx.conf (just copied above) are .gitignored / untracked so they survive
# the reset; if anything else was edited in the working tree it's lost
# *on purpose* — the deploy must be reproducible.
# ---------------------------------------------------------------------------
log "fetching main repo and checking out $BRANCH"
git fetch --prune origin
git checkout -B "$BRANCH" "origin/$BRANCH"
git reset --hard "origin/$BRANCH"
SHA="$(git rev-parse --short HEAD)"
log "main repo is at $SHA"

# Re-apply the config copies *after* the reset in case they happened to be
# tracked at some point (paranoia).
if [[ -f "$DEPLOY_DEPLOYMENT_DIR/config.json" ]]; then
    cp "$DEPLOY_DEPLOYMENT_DIR/config.json" "$DEPLOY_DIR/config.json"
fi
if [[ -f "$DEPLOY_DEPLOYMENT_DIR/nginx.conf" ]]; then
    cp "$DEPLOY_DEPLOYMENT_DIR/nginx.conf" "$DEPLOY_DIR/nginx.conf"
fi

# ---------------------------------------------------------------------------
# Step 4 — rebuild and restart the prod compose stack.
# --build forces image rebuild for services whose context changed.
# --remove-orphans cleans up services removed from compose since last deploy.
# ---------------------------------------------------------------------------
log "docker compose up --build (this may take a few minutes)"
docker compose "${COMPOSE_ARGS[@]}" up -d --build --remove-orphans

# ---------------------------------------------------------------------------
# Step 5 — health check.
# Bounded retry so a slow-starting container doesn't fail the deploy
# instantly, but an actually-broken release fails within ~90s.
# ---------------------------------------------------------------------------
if [[ "${SKIP_HEALTH:-0}" = "1" ]]; then
    log "SKIP_HEALTH=1 — skipping post-deploy health check"
    log "deploy complete (sha=$SHA, branch=$BRANCH, NOT health-verified)"
    exit 0
fi

log "waiting for $HEALTH_URL to return 200 (up to $((HEALTH_RETRIES * HEALTH_DELAY_S))s)"
for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    if curl -fsS --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
        log "health check passed on attempt $i"
        log "deploy complete (sha=$SHA, branch=$BRANCH)"
        exit 0
    fi
    sleep "$HEALTH_DELAY_S"
done

log "ERROR: health check failed after $HEALTH_RETRIES attempts — last status:"
curl -sS --max-time 5 -w '\nhttp=%{http_code}\n' "$HEALTH_URL" || true
log "docker compose ps:"
docker compose "${COMPOSE_ARGS[@]}" ps || true
log "last 50 api log lines:"
docker logs --tail 50 api 2>&1 || true
exit 1
