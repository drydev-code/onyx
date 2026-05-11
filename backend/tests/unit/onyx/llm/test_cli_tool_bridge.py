"""Tests for the CLI Tool Bridge helper.

Verifies that ``emit_bridge_packets`` converts bridged tool_call arguments
into the correct sequence of UI packets for each category, without ever
triggering real tool execution.
"""

import pytest

from onyx.llm.cli_tool_bridge import CATEGORY_FETCH
from onyx.llm.cli_tool_bridge import CATEGORY_FILE_READER
from onyx.llm.cli_tool_bridge import CATEGORY_INTERNAL_SEARCH
from onyx.llm.cli_tool_bridge import CATEGORY_INTERNET_SEARCH
from onyx.llm.cli_tool_bridge import emit_bridge_packets
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import FileReaderStart
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd


def _placement() -> Placement:
    return Placement(turn_index=0, tab_index=0, sub_turn_index=None, model_index=0)


def _collect(category: str, tool_name: str, arguments: str | None) -> list:
    return list(
        emit_bridge_packets(
            category=category,
            tool_name=tool_name,
            arguments=arguments,
            placement=_placement(),
        )
    )


# ---------------------------------------------------------------------------
# internet_search category
# ---------------------------------------------------------------------------


def test_internet_search_with_query() -> None:
    packets = _collect(
        CATEGORY_INTERNET_SEARCH, "WebSearch", '{"query": "amsterdam weather"}'
    )

    assert len(packets) == 3
    assert isinstance(packets[0].obj, SearchToolStart)
    assert packets[0].obj.is_internet_search is True
    assert isinstance(packets[1].obj, SearchToolQueriesDelta)
    assert packets[1].obj.queries == ["amsterdam weather"]
    assert isinstance(packets[2].obj, SectionEnd)


def test_internet_search_with_query_list() -> None:
    packets = _collect(
        CATEGORY_INTERNET_SEARCH,
        "WebSearch",
        '{"queries": ["foo", "bar"]}',
    )

    delta = [p for p in packets if isinstance(p.obj, SearchToolQueriesDelta)]
    assert len(delta) == 1
    assert delta[0].obj.queries == ["foo", "bar"]


def test_internet_search_without_query() -> None:
    packets = _collect(CATEGORY_INTERNET_SEARCH, "WebSearch", "{}")

    # start + end, no queries_delta when there is nothing to show.
    assert len(packets) == 2
    assert isinstance(packets[0].obj, SearchToolStart)
    assert isinstance(packets[1].obj, SectionEnd)


def test_internet_search_accepts_alternate_keys() -> None:
    # Some providers pass the query under a different key
    packets = _collect(
        CATEGORY_INTERNET_SEARCH, "WebSearch", '{"q": "python"}'
    )
    deltas = [p for p in packets if isinstance(p.obj, SearchToolQueriesDelta)]
    assert deltas and deltas[0].obj.queries == ["python"]


# ---------------------------------------------------------------------------
# internal_search category
# ---------------------------------------------------------------------------


def test_internal_search() -> None:
    packets = _collect(
        CATEGORY_INTERNAL_SEARCH,
        "mcp__onyx__search_indexed_documents",
        '{"query": "onboarding"}',
    )

    assert len(packets) == 3
    assert isinstance(packets[0].obj, SearchToolStart)
    assert packets[0].obj.is_internet_search is False
    assert isinstance(packets[1].obj, SearchToolQueriesDelta)
    assert packets[1].obj.queries == ["onboarding"]
    assert isinstance(packets[2].obj, SectionEnd)


# ---------------------------------------------------------------------------
# fetch category
# ---------------------------------------------------------------------------


def test_fetch_with_single_url() -> None:
    packets = _collect(
        CATEGORY_FETCH, "WebFetch", '{"url": "https://example.com"}'
    )

    assert len(packets) == 3
    assert isinstance(packets[0].obj, OpenUrlStart)
    assert isinstance(packets[1].obj, OpenUrlUrls)
    assert packets[1].obj.urls == ["https://example.com"]
    assert isinstance(packets[2].obj, SectionEnd)


def test_fetch_with_url_list() -> None:
    packets = _collect(
        CATEGORY_FETCH,
        "WebFetch",
        '{"urls": ["https://a.example", "https://b.example"]}',
    )

    urls_pkts = [p for p in packets if isinstance(p.obj, OpenUrlUrls)]
    assert len(urls_pkts) == 1
    assert urls_pkts[0].obj.urls == ["https://a.example", "https://b.example"]


def test_fetch_without_url() -> None:
    packets = _collect(CATEGORY_FETCH, "WebFetch", "{}")

    # start + end, no urls_delta when there is nothing to show.
    assert len(packets) == 2
    assert isinstance(packets[0].obj, OpenUrlStart)
    assert isinstance(packets[1].obj, SectionEnd)


# ---------------------------------------------------------------------------
# file_reader category
# ---------------------------------------------------------------------------


def test_file_reader() -> None:
    packets = _collect(
        CATEGORY_FILE_READER, "Read", '{"file_path": "/etc/hostname"}'
    )

    # file_reader emits just start+end -- no result packet because the CLI
    # provider doesn't have structured file metadata to populate it.
    assert len(packets) == 2
    assert isinstance(packets[0].obj, FileReaderStart)
    assert isinstance(packets[1].obj, SectionEnd)


# ---------------------------------------------------------------------------
# Error handling / edge cases
# ---------------------------------------------------------------------------


def test_unknown_category_yields_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    packets = _collect("bogus_category", "SomeTool", '{"x": 1}')
    assert packets == []


def test_malformed_json_degrades_gracefully() -> None:
    # Malformed JSON -> args dict is empty -> start+end with no query chip.
    packets = _collect(
        CATEGORY_INTERNET_SEARCH, "WebSearch", "{not valid json"
    )
    assert len(packets) == 2
    assert isinstance(packets[0].obj, SearchToolStart)
    assert isinstance(packets[1].obj, SectionEnd)


def test_none_arguments() -> None:
    packets = _collect(CATEGORY_INTERNET_SEARCH, "WebSearch", None)
    assert len(packets) == 2
    assert isinstance(packets[0].obj, SearchToolStart)
    assert isinstance(packets[1].obj, SectionEnd)


def test_non_dict_json_degrades_gracefully() -> None:
    # A JSON list is valid JSON but not a dict -- treat as empty args.
    packets = _collect(
        CATEGORY_INTERNET_SEARCH, "WebSearch", '["not", "a", "dict"]'
    )
    assert len(packets) == 2
