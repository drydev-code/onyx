from unittest.mock import MagicMock, patch

from onyx.chat.chat_state import ChatStateContainer
from onyx.context.search.models import SavedSearchDoc
from onyx.deep_research.models import CombinedResearchAgentCallResult
from onyx.llm.models import ReasoningEffort
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.fake_tools.research_agent import (
    build_research_agent_request,
    create_research_agent_citation_processor,
)
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.parallel_agents.models import (
    ParallelAgentPlan,
    ParallelAgentTask,
)
from onyx.tools.tool_implementations.parallel_agents.parallel_agent_tool import (
    ParallelAgentTool,
)


def test_worker_plan_passes_completed_reports_to_dependent_agents() -> None:
    emitter = MagicMock()
    emitter.is_cancelled.return_value = False
    llm = MagicMock()
    llm.config.max_input_tokens = 10000
    llm.config.model_name = "test-model"
    llm.config.model_provider = "test-provider"
    tool = ParallelAgentTool(
        tool_id=1,
        worker_tool_id=2,
        emitter=emitter,
        llm=llm,
    )
    tool.configure_runtime(
        state_container=ChatStateContainer(),
        tools=[],
        user_identity=None,
        reasoning_effort=ReasoningEffort.AUTO,
        agent_instructions=None,
    )
    plan = ParallelAgentPlan(
        tasks=[
            ParallelAgentTask(title="First", instruction="Find A"),
            ParallelAgentTask(title="Second", instruction="Find B"),
            ParallelAgentTask(
                title="Combine",
                instruction="Compare the findings",
                depends_on=[1, 2],
            ),
        ]
    )
    worker_calls = [
        ToolCallKickoff(
            tool_call_id=f"call-{index}",
            tool_name="research_agent",
            tool_args={"task": task.instruction, "title": task.title},
            placement=Placement(turn_index=1, tab_index=index),
        )
        for index, task in enumerate(plan.tasks, start=1)
    ]
    batch_results = [
        CombinedResearchAgentCallResult(
            intermediate_reports=["Report A", "Report B"],
            citation_mapping={},
        ),
        CombinedResearchAgentCallResult(
            intermediate_reports=["Combined report"],
            citation_mapping={},
        ),
    ]

    with (
        patch(
            "onyx.tools.tool_implementations.parallel_agents.parallel_agent_tool."
            "model_is_reasoning_model",
            return_value=False,
        ),
        patch(
            "onyx.tools.fake_tools.research_agent.run_research_agent_calls",
            side_effect=batch_results,
        ) as mock_run,
    ):
        result = tool._run_worker_plan(
            plan=plan,
            worker_calls=worker_calls,
            token_counter=len,
        )

    assert result.intermediate_reports == [
        "Report A",
        "Report B",
        "Combined report",
    ]
    assert mock_run.call_count == 2
    first_batch = mock_run.call_args_list[0].kwargs["research_agent_calls"]
    second_batch = mock_run.call_args_list[1].kwargs["research_agent_calls"]
    assert [call.tool_call_id for call in first_batch] == ["call-1", "call-2"]
    assert [call.tool_call_id for call in second_batch] == ["call-3"]
    dependency_context = second_batch[0].tool_args["context"]
    assert "## Task 1: First\nReport A" in dependency_context
    assert "## Task 2: Second\nReport B" in dependency_context
    assert "context" not in worker_calls[2].tool_args


def test_research_agent_request_includes_dependency_context() -> None:
    assert build_research_agent_request("Review the result", None) == (
        "Review the result"
    )
    assert build_research_agent_request("Review the result", "  First report  ") == (
        "Review the result\n\n"
        "Use these completed dependency reports as input:\n\n"
        "First report"
    )


def test_dependent_agent_reserves_existing_citation_numbers() -> None:
    existing_document = SavedSearchDoc.from_url("https://example.com/source")
    citation_processor = create_research_agent_citation_processor(
        {1: existing_document}
    )

    assert citation_processor.get_next_citation_number() == 2
