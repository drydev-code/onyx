"""CLI Tool Bridge — translate self-executed CLI tool calls into UI packets.

Claude Code CLI and Codex CLI execute tools (including Onyx MCP tools) inside
their own process. Their streams surface tool_use events we cannot re-execute
-- double-execution would hit the tool twice with potentially divergent
results.

This module translates specific tool_call deltas into the same rich packets
that a LiteLLM provider + Onyx tool execution would emit, so the frontend
timeline shows chips (SearchToolRenderer, FetchToolRenderer, etc.) without
kicking off real tool execution.

Used by ``llm_step.py`` via a small conditional branch when
``LLMConfig.cli_tool_bridge`` is set. Bridged tool_calls are NEVER added to
the kickoff map -- they're consumed entirely here.
"""
from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import FileReaderStart
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Bridge categories (values in ``LLMConfig.cli_tool_bridge`` maps).
CATEGORY_INTERNET_SEARCH = "internet_search"
CATEGORY_INTERNAL_SEARCH = "internal_search"
CATEGORY_FETCH = "fetch"
CATEGORY_FILE_READER = "file_reader"

_VALID_CATEGORIES = frozenset(
    [
        CATEGORY_INTERNET_SEARCH,
        CATEGORY_INTERNAL_SEARCH,
        CATEGORY_FETCH,
        CATEGORY_FILE_READER,
    ]
)


def _parse_args(arguments: str | None) -> dict[str, Any]:
    """Parse a tool_call ``arguments`` string into a dict.

    Returns an empty dict on any parse error or non-dict payload.
    """
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_first(
    args: dict[str, Any], keys: tuple[str, ...]
) -> list[str]:
    """Return the first non-empty value from ``args`` for any of ``keys``.

    String values are wrapped in a single-element list; list values are
    returned as-is (coerced to strings). Used to pull query strings and URL
    strings out of heterogeneous tool argument shapes.
    """
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list) and value:
            return [str(v) for v in value if v]
    return []


def emit_bridge_packets(
    category: str,
    tool_name: str,
    arguments: str | None,
    placement: Placement,
) -> Generator[Packet, None, None]:
    """Yield the rich UI packets that match a bridged tool call.

    Called from ``llm_step.py`` when a provider with ``cli_tool_bridge`` set
    yields a tool_call matching one of its keys. Emits start/deltas/end
    packets for the chip UI, then returns. The caller must NOT also add this
    tool to the kickoff map.
    """
    if category not in _VALID_CATEGORIES:
        logger.warning(
            "cli_tool_bridge: unknown category %r for tool %r; skipping.",
            category,
            tool_name,
        )
        return

    args = _parse_args(arguments)

    if category == CATEGORY_INTERNET_SEARCH:
        yield Packet(
            placement=placement,
            obj=SearchToolStart(is_internet_search=True),
        )
        queries = _extract_first(
            args, ("query", "q", "search_query", "queries")
        )
        if queries:
            yield Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        yield Packet(placement=placement, obj=SectionEnd())
        return

    if category == CATEGORY_INTERNAL_SEARCH:
        yield Packet(
            placement=placement,
            obj=SearchToolStart(is_internet_search=False),
        )
        queries = _extract_first(
            args, ("query", "q", "search_query", "queries")
        )
        if queries:
            yield Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(queries=queries),
            )
        yield Packet(placement=placement, obj=SectionEnd())
        return

    if category == CATEGORY_FETCH:
        yield Packet(placement=placement, obj=OpenUrlStart())
        urls = _extract_first(args, ("url", "urls", "link"))
        if urls:
            yield Packet(placement=placement, obj=OpenUrlUrls(urls=urls))
        yield Packet(placement=placement, obj=SectionEnd())
        return

    if category == CATEGORY_FILE_READER:
        yield Packet(placement=placement, obj=FileReaderStart())
        yield Packet(placement=placement, obj=SectionEnd())
        return
