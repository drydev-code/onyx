#!/bin/bash
# deploy-dev.sh - Fast build and deploy to onyx server
#
# Usage:
#   ./deploy-dev.sh              # Build and deploy both backend + web
#   ./deploy-dev.sh backend      # Build and deploy backend only
#   ./deploy-dev.sh web          # Build and deploy web only
#   ./deploy-dev.sh reset        # Wipe craft-base + craft-latest, force a
#                                #   full backend rebuild on the next run
#
# First run takes the same time as normal (builds the base image).
# Subsequent runs after code changes take ~30s for backend, ~2-3min for web.
#
# Layer-depth note: each Dockerfile.dev build adds one layer on top of its
# BASE_IMAGE.  We pin BASE_IMAGE to an immutable ``craft-base`` tag (only
# rebuilt by the full Dockerfile path) so dev rebuilds never stack on top
# of each other — that previously hit Docker's ~125-layer cap and broke
# pushes with "max depth exceeded" after ~115 dev iterations.

set -e

SSH_KEY="$HOME/.ssh/id_ed25519"
SSH_HOST="root@onyx"
SSH="ssh -i $SSH_KEY $SSH_HOST"
BACKEND_BASE_TAG="onyxdotapp/onyx-backend:craft-base"
BACKEND_TAG="onyxdotapp/onyx-backend:craft-latest"
WEB_TAG="onyxdotapp/onyx-web-server:craft-latest"

TARGET="${1:-both}"

build_backend() {
    echo "==> Building backend (dev mode - code overlay only)..."
    cd "$(dirname "$0")/backend"

    # Step 1: ensure an immutable base image exists.  This is the FULL
    # Dockerfile build and includes all Python deps — slow, but only runs
    # the first time or after a ``reset``.
    if ! docker image inspect "$BACKEND_BASE_TAG" >/dev/null 2>&1; then
        echo "    No base image found, doing full build → $BACKEND_BASE_TAG"
        docker build -t "$BACKEND_BASE_TAG" \
            --build-arg ENABLE_CRAFT=true \
            --build-arg ENABLE_CLI_PROVIDERS=true \
            -f Dockerfile .
    fi

    # Step 2: overlay the application code on top of the immutable base.
    # ALWAYS use $BACKEND_BASE_TAG as the BASE_IMAGE (never $BACKEND_TAG)
    # so successive dev rebuilds don't stack layers on each other.
    echo "    Using Dockerfile.dev (fast rebuild on $BACKEND_BASE_TAG)"
    docker build -t "$BACKEND_TAG" \
        --build-arg BASE_IMAGE="$BACKEND_BASE_TAG" \
        --build-arg ENABLE_CRAFT=true \
        --build-arg ENABLE_CLI_PROVIDERS=true \
        -f Dockerfile.dev .
}

build_web() {
    echo "==> Building web (dev mode - cached deps + incremental build)..."
    cd "$(dirname "$0")/web"
    docker build -t "$WEB_TAG" -f Dockerfile.dev .
}

push_and_restart() {
    local services=""

    if [ "$TARGET" = "both" ] || [ "$TARGET" = "backend" ]; then
        echo "==> Pushing backend image..."
        docker save "$BACKEND_TAG" | $SSH "docker load"
        services="api_server background"
    fi

    if [ "$TARGET" = "both" ] || [ "$TARGET" = "web" ]; then
        echo "==> Pushing web image..."
        docker save "$WEB_TAG" | $SSH "docker load"
        services="$services web_server"
    fi

    echo "==> Restarting services: $services"
    $SSH "cd /var/onyx/onyx_data/deployment && docker compose up -d --force-recreate $services && docker compose restart nginx"

    echo "==> Waiting for health check..."
    sleep 30
    $SSH "docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'api_server|web_server|nginx'"
    echo "==> Deploy complete!"
}

case "$TARGET" in
    backend)
        build_backend
        push_and_restart
        ;;
    web)
        build_web
        push_and_restart
        ;;
    both)
        build_backend &
        BACKEND_PID=$!
        build_web &
        WEB_PID=$!
        wait $BACKEND_PID $WEB_PID
        push_and_restart
        ;;
    reset)
        echo "==> Removing $BACKEND_BASE_TAG and $BACKEND_TAG..."
        docker image rm -f "$BACKEND_BASE_TAG" "$BACKEND_TAG" 2>/dev/null || true
        echo "==> Done.  Next ./deploy-dev.sh run will do a full backend"
        echo "    rebuild from Dockerfile (slow, but resets layer depth)."
        ;;
    *)
        echo "Usage: $0 [backend|web|both|reset]"
        exit 1
        ;;
esac
