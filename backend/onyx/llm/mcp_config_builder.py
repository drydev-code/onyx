"""Build MCP configuration for the Claude Code CLI from Onyx's database.

Reads connected MCP servers and converts them into the JSON format
expected by ``claude --mcp-config``.
"""

from sqlalchemy.orm import Session

from onyx.configs.app_configs import MCP_SERVER_ENABLED
from onyx.configs.app_configs import MCP_SERVER_PORT
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_all_mcp_servers
from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_mcp_config_for_cli(db_session: Session) -> dict:
    """Build an MCP config dict compatible with Claude Code CLI's --mcp-config format.

    Reads all CONNECTED MCP servers from the database and converts them
    to the format expected by the Claude CLI::

        {
            "mcpServers": {
                "server-name": {
                    "url": "https://...",
                    "headers": {"Authorization": "Bearer ..."}
                }
            }
        }

    Returns an empty dict when no servers are available.
    """
    mcp_servers: dict[str, dict] = {}

    try:
        all_servers = get_all_mcp_servers(db_session)
    except Exception:
        logger.warning(
            "Failed to fetch MCP servers from database; "
            "CLI will run without auto-configured MCP servers."
        )
        return {}

    for server in all_servers:
        if server.status != MCPServerStatus.CONNECTED:
            continue

        # Get connection data (headers, tokens) from admin config
        connection_data = extract_connection_data(
            server.admin_connection_config
        )
        headers = dict(connection_data.get("headers", {}))

        transport = server.transport
        server_name = server.name.strip().replace(" ", "-").lower()

        if transport == MCPTransport.STDIO:
            # STDIO transport: needs command + args
            # The server_url field stores the command for STDIO servers
            entry: dict = {
                "command": server.server_url,
                "args": [],
            }
        else:
            # SSE or STREAMABLE_HTTP: use url + headers
            entry = {
                "url": server.server_url,
            }
            if headers:
                entry["headers"] = headers

        mcp_servers[server_name] = entry

    # Include Onyx's own MCP server if enabled
    if MCP_SERVER_ENABLED:
        mcp_servers["onyx"] = {
            "url": f"http://localhost:{MCP_SERVER_PORT}/sse",
        }

    if not mcp_servers:
        return {}

    return {"mcpServers": mcp_servers}
