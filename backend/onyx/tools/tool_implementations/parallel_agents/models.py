from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from onyx.chat.citation_processor import CitationMapping
from onyx.context.search.models import SearchDoc, SearchDocsResponse

MAX_PARALLEL_AGENTS = 5


class ParallelAgentTask(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=20000)
    depends_on: list[int] = Field(
        default_factory=list,
        max_length=MAX_PARALLEL_AGENTS,
        description=(
            "One-based task numbers that must finish before this task starts. "
            "Dependencies must refer to earlier tasks."
        ),
    )

    @field_validator("title", "instruction")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("depends_on")
    @classmethod
    def normalize_dependencies(cls, value: list[int]) -> list[int]:
        if any(dependency < 1 for dependency in value):
            raise ValueError("Task dependencies must be positive task numbers")
        return sorted(set(value))


class ParallelAgentPlan(BaseModel):
    tasks: list[ParallelAgentTask] = Field(
        min_length=1,
        max_length=MAX_PARALLEL_AGENTS,
    )

    @model_validator(mode="after")
    def validate_dependency_order(self) -> "ParallelAgentPlan":
        for task_number, task in enumerate(self.tasks, start=1):
            invalid_dependencies = [
                dependency
                for dependency in task.depends_on
                if dependency >= task_number
            ]
            if invalid_dependencies:
                raise ValueError(
                    f"Task {task_number} dependencies must refer to earlier tasks"
                )
        return self


def parse_parallel_agent_plan(tool_arguments: dict[str, Any]) -> ParallelAgentPlan:
    capped_arguments = dict(tool_arguments)
    raw_tasks = capped_arguments.get("tasks")
    if isinstance(raw_tasks, list):
        capped_arguments["tasks"] = raw_tasks[:MAX_PARALLEL_AGENTS]
    return ParallelAgentPlan.model_validate(capped_arguments)


def format_parallel_agent_plan(plan: ParallelAgentPlan) -> str:
    lines = []
    for index, task in enumerate(plan.tasks, start=1):
        dependency_text = ""
        if task.depends_on:
            dependencies = ", ".join(str(value) for value in task.depends_on)
            dependency_text = f" (after {dependencies})"
        lines.append(f"{index}. **{task.title}**{dependency_text} — {task.instruction}")
    return "\n".join(lines)


def build_parallel_agent_execution_batches(
    plan: ParallelAgentPlan,
) -> list[list[int]]:
    """Return zero-based task indexes grouped by dependency readiness."""
    remaining = set(range(len(plan.tasks)))
    completed: set[int] = set()
    batches: list[list[int]] = []

    while remaining:
        ready = sorted(
            task_index
            for task_index in remaining
            if all(
                dependency - 1 in completed
                for dependency in plan.tasks[task_index].depends_on
            )
        )
        if not ready:
            raise ValueError("Parallel agent plan has unresolved task dependencies")
        batches.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)

    return batches


def truncate_text_to_token_budget(
    text: str,
    token_budget: int,
    token_counter: Callable[[str], int],
) -> str:
    if token_budget <= 0:
        return ""
    if token_counter(text) <= token_budget:
        return text

    low = 0
    high = len(text)
    while low < high:
        midpoint = (low + high + 1) // 2
        if token_counter(text[:midpoint]) <= token_budget:
            low = midpoint
        else:
            high = midpoint - 1

    truncated = text[:low].rstrip()
    return f"{truncated}\n[truncated]" if truncated else "[truncated]"


def build_parallel_agent_search_response(
    citation_mapping: CitationMapping,
    cited_mapping: CitationMapping,
) -> SearchDocsResponse:
    documents_by_id: dict[str, SearchDoc] = {}
    for document in citation_mapping.values():
        documents_by_id.setdefault(document.document_id, document)

    displayed_by_id: dict[str, SearchDoc] = {}
    for document in cited_mapping.values():
        displayed_by_id.setdefault(document.document_id, document)

    return SearchDocsResponse(
        search_docs=list(documents_by_id.values()),
        citation_mapping={
            citation_number: document.document_id
            for citation_number, document in citation_mapping.items()
        },
        displayed_docs=list(displayed_by_id.values()) or None,
    )
