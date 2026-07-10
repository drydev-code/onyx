#!/bin/bash
# deploy-dev.sh - Fast build and deploy to onyx server
#
# Usage:
#   ./deploy-dev.sh              # Server-side build + restart of backend AND web
#   ./deploy-dev.sh backend      # Server-side build + restart of backend only
#   ./deploy-dev.sh web          # Server-side build + restart of web only
#   ./deploy-dev.sh reset        # Wipe craft-base + craft-latest on the server,
#                                #   forcing a full backend rebuild on next run
#   ./deploy-dev.sh local        # Legacy path: build locally, ship via
#                                #   ``docker save | ssh docker load`` (slow,
#                                #   useful if the server is under load)
#
# Default flow (server-side build):
#   1. SSH to root@onyx, ensure git is installed and the fork is cloned at
#      $SERVER_REPO_DIR.
#   2. ``git fetch origin && git reset --hard origin/$DEPLOY_BRANCH``
#   3. Build backend (Dockerfile.dev on top of immutable craft-base) and/or
#      web (Dockerfile.dev) on the server itself.
#   4. ``docker compose up -d --force-recreate <services>`` in the deployment
#      dir + restart nginx.
#
# DEPLOY_BRANCH defaults to ``integration/merged`` — override via env var:
#   DEPLOY_BRANCH=feature/foo ./deploy-dev.sh both
#
# Push your local commits before running — the server pulls from origin, it
# does NOT receive your working tree.
#
# Layer-depth note: each Dockerfile.dev build adds one layer on top of its
# BASE_IMAGE.  We pin BASE_IMAGE to an immutable ``craft-base`` tag (only
# rebuilt by the full Dockerfile path, or by ``./deploy-dev.sh reset``) so dev
# rebuilds never stack on top of each other — that previously hit Docker's
# ~125-layer cap and broke pushes with "max depth exceeded" after ~115 dev
# iterations.

set -e

SSH_KEY="$HOME/.ssh/id_ed25519"
SSH_HOST="root@onyx"
SSH="ssh -i $SSH_KEY $SSH_HOST"

SERVER_REPO_DIR="/var/onyx/onyx_data/onyx-src"
DEPLOYMENT_DIR="/var/onyx/onyx_data/deployment"
REPO_URL="https://github.com/drydev-code/onyx.git"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-integration/merged}"

BACKEND_BASE_TAG="onyxdotapp/onyx-backend:craft-base"
BACKEND_TAG="onyxdotapp/onyx-backend:craft-latest"
WEB_TAG="onyxdotapp/onyx-web-server:craft-latest"

TARGET="${1:-both}"

# ---------------------------------------------------------------------------
# Server-side helpers
# ---------------------------------------------------------------------------

ensure_server_prereqs() {
    # Alpine images on the server may not have git installed.  Install it on
    # demand so the bootstrap is one-shot.
    $SSH 'command -v git >/dev/null 2>&1 || { echo "    Installing git on server..."; apk add --no-cache git >/dev/null; }'
}

ensure_server_repo() {
    ensure_server_prereqs
    if $SSH "test -d $SERVER_REPO_DIR/.git"; then
        # Make sure origin points at the fork — if someone pre-cloned upstream
        # by accident the fetch below would pull the wrong branch.
        $SSH "cd $SERVER_REPO_DIR && git remote set-url origin $REPO_URL"
    else
        echo "==> Bootstrapping repo on server at $SERVER_REPO_DIR..."
        $SSH "mkdir -p $(dirname "$SERVER_REPO_DIR") && git clone $REPO_URL $SERVER_REPO_DIR"
    fi
}

sync_server_repo() {
    echo "==> Syncing server repo to origin/$DEPLOY_BRANCH..."
    $SSH "cd $SERVER_REPO_DIR && git fetch --prune origin && git reset --hard origin/$DEPLOY_BRANCH && git log -1 --oneline"
}

ensure_backend_base_remote() {
    # The immutable base image holds the slow Python deps install.  Built
    # once from the FULL Dockerfile, then reused as BASE_IMAGE for every
    # Dockerfile.dev rebuild.
    if $SSH "docker image inspect $BACKEND_BASE_TAG >/dev/null 2>&1"; then
        return
    fi
    echo "==> No base image on server, doing full build → $BACKEND_BASE_TAG"
    $SSH "cd $SERVER_REPO_DIR/backend && docker build -t $BACKEND_BASE_TAG \
        --build-arg ENABLE_CRAFT=true \
        --build-arg ENABLE_CLI_PROVIDERS=true \
        -f Dockerfile ."
}

build_backend_remote() {
    ensure_backend_base_remote
    echo "==> Building backend on server (Dockerfile.dev on $BACKEND_BASE_TAG)..."
    $SSH "cd $SERVER_REPO_DIR/backend && docker build -t $BACKEND_TAG \
        --build-arg BASE_IMAGE=$BACKEND_BASE_TAG \
        --build-arg ENABLE_CRAFT=true \
        --build-arg ENABLE_CLI_PROVIDERS=true \
        -f Dockerfile.dev ."
}

build_web_remote() {
    echo "==> Building web on server (Dockerfile.dev)..."
    $SSH "cd $SERVER_REPO_DIR/web && docker build -t $WEB_TAG -f Dockerfile.dev ."
}

restart_services_remote() {
    local services="$1"
    echo "==> Restarting services: $services"
    $SSH "cd $DEPLOYMENT_DIR && docker compose up -d --force-recreate $services && docker compose restart nginx"

    echo "==> Waiting for health check..."
    sleep 30
    $SSH "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'api_server|web_server|background|nginx' || true"
    echo "==> Deploy complete!"
}

# ---------------------------------------------------------------------------
# Local-build fallback (original flow — slow, ships images via docker save)
# ---------------------------------------------------------------------------

build_backend_local() {
    echo "==> [local] Building backend (dev mode - code overlay only)..."
    cd "$(dirname "$0")/backend"

    if ! docker image inspect "$BACKEND_BASE_TAG" >/dev/null 2>&1; then
        echo "    No base image found, doing full build → $BACKEND_BASE_TAG"
        docker build -t "$BACKEND_BASE_TAG" \
            --build-arg ENABLE_CRAFT=true \
            --build-arg ENABLE_CLI_PROVIDERS=true \
            -f Dockerfile .
    fi

    echo "    Using Dockerfile.dev (fast rebuild on $BACKEND_BASE_TAG)"
    docker build -t "$BACKEND_TAG" \
        --build-arg BASE_IMAGE="$BACKEND_BASE_TAG" \
        --build-arg ENABLE_CRAFT=true \
        --build-arg ENABLE_CLI_PROVIDERS=true \
        -f Dockerfile.dev .
}

build_web_local() {
    echo "==> [local] Building web (dev mode - cached deps + incremental build)..."
    cd "$(dirname "$0")/web"
    docker build -t "$WEB_TAG" -f Dockerfile.dev .
}

push_and_restart_local() {
    echo "==> [local] Pushing backend image..."
    docker save "$BACKEND_TAG" | $SSH "docker load"
    echo "==> [local] Pushing web image..."
    docker save "$WEB_TAG" | $SSH "docker load"
    restart_services_remote "api_server background web_server"
}

run_local() {
    build_backend_local &
    BACKEND_PID=$!
    build_web_local &
    WEB_PID=$!
    wait $BACKEND_PID $WEB_PID
    push_and_restart_local
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "$TARGET" in
    backend)
        ensure_server_repo
        sync_server_repo
        build_backend_remote
        restart_services_remote "api_server background"
        ;;
    web)
        ensure_server_repo
        sync_server_repo
        build_web_remote
        restart_services_remote "web_server"
        ;;
    both)
        ensure_server_repo
        sync_server_repo
        build_backend_remote
        build_web_remote
        restart_services_remote "api_server background web_server"
        ;;
    reset)
        echo "==> Removing $BACKEND_BASE_TAG and $BACKEND_TAG on server..."
        $SSH "docker image rm -f $BACKEND_BASE_TAG $BACKEND_TAG 2>/dev/null || true"
        echo "==> Done.  Next ./deploy-dev.sh run will do a full backend"
        echo "    rebuild from Dockerfile (slow, but resets layer depth)."
        ;;
    local)
        run_local
        ;;
    *)
        echo "Usage: $0 [backend|web|both|reset|local]"
        exit 1
        ;;
esac
