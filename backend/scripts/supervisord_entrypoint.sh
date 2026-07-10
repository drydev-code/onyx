#!/bin/sh
# Entrypoint script for supervisord

# Refresh the Claude Code / Codex CLIs. No-op unless ENABLE_CLI_PROVIDERS=true,
# and never fatal -- see scripts/update_cli_providers.sh.
if [ -x /app/scripts/update_cli_providers.sh ]; then
    /app/scripts/update_cli_providers.sh || true
fi

# Launch supervisord with environment variables available
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
