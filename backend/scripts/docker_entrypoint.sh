#!/bin/sh
# Image-wide entrypoint for the backend container.
#
# Runs before whatever `command:` the deployment supplies (uvicorn, supervisord,
# celery, ...) and then execs it. This is the only place the CLI refresh can
# live and still cover every container: api_server runs uvicorn directly in some
# compose files, while background goes through supervisord_entrypoint.sh.
#
# Keep this hook cheap and non-fatal — it sits in front of every backend process.

if [ -x /app/scripts/update_cli_providers.sh ]; then
    /app/scripts/update_cli_providers.sh || true
fi

exec "$@"
