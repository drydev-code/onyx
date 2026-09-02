from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from onyx.db.models import ToolCall
from onyx.server.query_and_chat.session_loading import create_parallel_agent_packets
from onyx.server.query_and_chat.streaming_models import (
    DeepResearchPlanDelta,
    DeepResearchPlanStart,
    IntermediateReportDelta,
    ResearchAgentStart,
    SearchToolStart,
    SectionEnd,
    TopLevelBranching,
)
from onyx.tools.tool_implementations.parallel_agents.parallel_agent_tool import (
    filter_parallel_agent_worker_tools,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def _tool_call_mock() -> MagicMock:
    return MagicMock(spec=ToolCall)


def test_parallel_agent_workers_only_receive_read_only_tools() -> None:
    search_tool = MagicMock(spec=SearchTool)
    python_tool = MagicMock(spec=PythonTool)

    assert filter_parallel_agent_worker_tools([search_tool, python_tool]) == [
        search_tool
    ]


def test_parallel_agent_replay_restores_plan_workers_and_synthesis() -> None:
    nested_search = _tool_call_mock()
    nested_search.id = 30
    nested_search.tool_id = 40
    nested_search.turn_number = 2
    nested_search.tab_index = 1
    nested_search.tool_call_arguments = {"queries": ["first requirement"]}
    nested_search.search_docs = []

    first_worker = _tool_call_mock()
    first_worker.tab_index = 1
    first_worker.tool_call_arguments = {
        "title": "First task",
        "task": "Inspect the first requirement.",
    }
    first_worker.tool_call_response = "First report"
    first_worker.tool_call_children = [nested_search]

    second_worker = _tool_call_mock()
    second_worker.tab_index = 2
    second_worker.tool_call_arguments = {
        "title": "Second task",
        "task": "Inspect the second requirement.",
    }
    second_worker.tool_call_response = "Second report"
    second_worker.tool_call_children = []

    outer_call = _tool_call_mock()
    outer_call.tab_index = 0
    outer_call.tool_call_children = [second_worker, first_worker]
    outer_call.tool_call_response = "Combined result"
    outer_call.search_docs = []

    with patch(
        "onyx.server.query_and_chat.session_loading.get_tool_by_id",
        return_value=SimpleNamespace(in_code_tool_id="SearchTool"),
    ):
        packets = create_parallel_agent_packets(
            outer_call,
            turn_index=3,
            db_session=MagicMock(spec=Session),
        )

    assert isinstance(packets[0].obj, TopLevelBranching)
    assert packets[0].obj.num_parallel_branches == 4
    assert isinstance(packets[1].obj, DeepResearchPlanStart)
    assert isinstance(packets[2].obj, DeepResearchPlanDelta)
    assert "First task" in packets[2].obj.content

    worker_starts = [
        packet for packet in packets if isinstance(packet.obj, ResearchAgentStart)
    ]
    assert [packet.placement.tab_index for packet in worker_starts] == [1, 2, 3]

    nested_search_start = next(
        packet for packet in packets if isinstance(packet.obj, SearchToolStart)
    )
    assert nested_search_start.placement.tab_index == 1
    assert nested_search_start.placement.sub_turn_index == 2

    reports = [
        packet.obj.content
        for packet in packets
        if isinstance(packet.obj, IntermediateReportDelta)
    ]
    assert reports == ["First report", "Second report", "Combined result"]
    assert isinstance(packets[-1].obj, SectionEnd)
