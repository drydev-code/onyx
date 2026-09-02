import pytest
from pydantic import ValidationError

from onyx.context.search.models import SavedSearchDoc
from onyx.tools.tool_implementations.parallel_agents.models import (
    ParallelAgentPlan,
    ParallelAgentTask,
    build_parallel_agent_execution_batches,
    build_parallel_agent_search_response,
    format_parallel_agent_plan,
    parse_parallel_agent_plan,
    truncate_text_to_token_budget,
)


def test_parallel_agent_plan_accepts_five_tasks_and_formats_them() -> None:
    plan = ParallelAgentPlan(
        tasks=[
            ParallelAgentTask(title=f" Task {index} ", instruction=" Do work ")
            for index in range(1, 6)
        ]
    )

    assert plan.tasks[0].title == "Task 1"
    assert plan.tasks[0].instruction == "Do work"
    assert format_parallel_agent_plan(plan).splitlines()[0] == (
        "1. **Task 1** — Do work"
    )


def test_parallel_agent_plan_rejects_more_than_five_tasks() -> None:
    with pytest.raises(ValidationError):
        ParallelAgentPlan(
            tasks=[
                ParallelAgentTask(title=f"Task {index}", instruction="Do work")
                for index in range(6)
            ]
        )


def test_parallel_agent_tool_arguments_cap_planner_output_at_five_tasks() -> None:
    plan = parse_parallel_agent_plan(
        {
            "tasks": [
                {"title": f"Task {index}", "instruction": "Do work"}
                for index in range(6)
            ]
        }
    )

    assert len(plan.tasks) == 5


def test_parallel_agent_plan_builds_parallel_and_sequential_batches() -> None:
    plan = ParallelAgentPlan(
        tasks=[
            ParallelAgentTask(title="First", instruction="Do first"),
            ParallelAgentTask(title="Second", instruction="Do second"),
            ParallelAgentTask(
                title="Combine",
                instruction="Use both results",
                depends_on=[2, 1, 1],
            ),
            ParallelAgentTask(
                title="Review",
                instruction="Review the combined result",
                depends_on=[3],
            ),
        ]
    )

    assert plan.tasks[2].depends_on == [1, 2]
    assert build_parallel_agent_execution_batches(plan) == [[0, 1], [2], [3]]
    assert "3. **Combine** (after 1, 2)" in format_parallel_agent_plan(plan)


@pytest.mark.parametrize("dependency", [0, -1, 1, 2])
def test_parallel_agent_plan_rejects_invalid_dependencies(dependency: int) -> None:
    with pytest.raises(ValidationError):
        tasks = [ParallelAgentTask(title="First", instruction="Do first")]
        if dependency == 2:
            tasks.append(
                ParallelAgentTask(
                    title="Second",
                    instruction="Do second",
                    depends_on=[2],
                )
            )
        else:
            tasks[0] = ParallelAgentTask(
                title="First",
                instruction="Do first",
                depends_on=[dependency],
            )
        ParallelAgentPlan(tasks=tasks)


def test_truncate_text_to_token_budget_marks_truncated_content() -> None:
    def token_counter(text: str) -> int:
        return len(text)

    assert truncate_text_to_token_budget("abcdef", 10, token_counter) == "abcdef"
    assert truncate_text_to_token_budget("abcdef", 3, token_counter) == (
        "abc\n[truncated]"
    )
    assert truncate_text_to_token_budget("abcdef", 0, token_counter) == ""


def test_search_response_deduplicates_documents_and_keeps_citation_numbers() -> None:
    first = SavedSearchDoc.from_url("https://example.com/first")
    second = SavedSearchDoc.from_url("https://example.com/second")

    response = build_parallel_agent_search_response(
        citation_mapping={1: first, 2: first, 3: second},
        cited_mapping={2: first},
    )

    assert [document.document_id for document in response.search_docs] == [
        first.document_id,
        second.document_id,
    ]
    assert response.citation_mapping == {
        1: first.document_id,
        2: first.document_id,
        3: second.document_id,
    }
    assert response.displayed_docs == [first]
