#!/bin/sh
# Refresh the CLI-provider binaries (Claude Code, Codex) on container start.
#
# The image bakes in whatever was newest at build time. Both CLIs ship frequent
# releases, and neither self-updates reliably here: the npm globals live in a
# root-owned prefix while the providers run the binaries as the unprivileged
# `onyx` user, so the vendors' built-in updaters cannot write to them.
#
# This runs once per container start, before supervisord takes over.
#
# Environment:
#   ENABLE_CLI_PROVIDERS       - "true" when the CLIs are present (set by the image)
#   CLI_PROVIDERS_AUTO_UPDATE  - "false" to skip the refresh (default: true)
#   CLI_PROVIDERS_UPDATE_TIMEOUT - seconds to allow for the npm install (default: 180)
#
# Never fatal: a registry outage or an offline host must not stop the API server
# from booting, it just keeps the version baked into the image.

set -u

if [ "${ENABLE_CLI_PROVIDERS:-false}" != "true" ]; then
    exit 0
fi

if [ "${CLI_PROVIDERS_AUTO_UPDATE:-true}" != "true" ]; then
    echo "[cli-providers] auto-update disabled; keeping the image's CLI versions"
    exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "[cli-providers] npm not found; skipping CLI refresh"
    exit 0
fi

timeout_secs="${CLI_PROVIDERS_UPDATE_TIMEOUT:-180}"

echo "[cli-providers] refreshing Claude Code and Codex CLIs..."
if timeout "$timeout_secs" npm install -g --no-fund --no-audit \
        @anthropic-ai/claude-code@latest \
        @openai/codex@latest; then
    # The providers run these as the `onyx` user; keep its config dirs writable.
    mkdir -p /home/onyx/.claude /home/onyx/.codex 2>/dev/null || true
    chown -R onyx:onyx /home/onyx/.claude /home/onyx/.codex 2>/dev/null || true
    echo "[cli-providers] claude: $(claude --version 2>/dev/null || echo unknown)"
    echo "[cli-providers] codex:  $(codex --version 2>/dev/null || echo unknown)"
else
    echo "[cli-providers] refresh failed (offline or registry error);" \
         "continuing with the versions baked into the image" >&2
fi

exit 0
