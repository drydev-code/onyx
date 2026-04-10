"""Build MCP configuration for a future Codex CLI provider from Onyx's database.

Reads connected MCP servers and converts them into the TOML format
expected by Codex CLI's ``config.toml``.

This module is not wired into any provider yet. It exists to document
the pattern and be ready when a Codex CLI subprocess provider is added.
"""

from sqlalchemy.orm import Session

from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_all_mcp_servers
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _escape_toml_string(value: str) -> str:
    """Escape a string for use as a TOML basic string value.

    Handles backslashes, double quotes, and common control characters.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


def build_codex_mcp_config(db_session: Session) -> str:
    """Build a TOML config string for Codex CLI's MCP servers.

    Reads CONNECTED MCP servers from Onyx's database and converts them
    to Codex's config.toml format::

        [mcp_servers.server-name]
        url = "https://..."
        http_headers = { "Authorization" = "Bearer ..." }

    Only HTTP-based transports (SSE, STREAMABLE_HTTP) are included.
    STDIO servers are skipped because Codex CLI's config.toml format
    uses a different mechanism for local/command-based servers.

    Returns an empty string when no servers are available.
    """
    sections: list[str] = []

    try:
        all_servers = get_all_mcp_servers(db_session)
    except Exception:
        logger.warning(
            "Failed to fetch MCP servers from database; "
            "Codex config will have no MCP servers."
        )
        return ""

    for server in all_servers:
        if server.status != MCPServerStatus.CONNECTED:
            continue

        # Skip STDIO servers -- Codex config.toml uses url-based entries
        if server.transport == MCPTransport.STDIO:
            logger.debug(
                "Skipping STDIO MCP server '%s' for Codex config "
                "(only HTTP transports supported).",
                server.name,
            )
            continue

        connection_data = extract_connection_data(server.admin_connection_config)
        headers = dict(connection_data.get("headers", {}))

        # Normalise server name to a valid TOML key
        server_name = server.name.strip().replace(" ", "-").lower()

        lines: list[str] = []
        lines.append(f'[mcp_servers."{_escape_toml_string(server_name)}"]')
        lines.append(f'url = "{_escape_toml_string(server.server_url)}"')

        if headers:
            # Inline table: { "Key1" = "Val1", "Key2" = "Val2" }
            pairs = ", ".join(
                f'"{_escape_toml_string(k)}" = "{_escape_toml_string(v)}"'
                for k, v in headers.items()
            )
            lines.append(f"http_headers = {{ {pairs} }}")

        sections.append("\n".join(lines))

    if not sections:
        return ""

    return "\n\n".join(sections) + "\n"
