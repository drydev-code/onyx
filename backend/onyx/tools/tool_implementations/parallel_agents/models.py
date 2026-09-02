from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, field_validator

from onyx.chat.citation_processor import CitationMapping
from onyx.context.search.models import SearchDoc, SearchDocsResponse

MAX_PARALLEL_AGENTS = 5


class ParallelAgentTask(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "instruction")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ParallelAgentPlan(BaseModel):
    tasks: list[ParallelAgentTask] = Field(
        min_length=1,
        max_length=MAX_PARALLEL_AGENTS,
    )


def parse_parallel_agent_plan(tool_arguments: dict[str, Any]) -> ParallelAgentPlan:
    capped_arguments = dict(tool_arguments)
    raw_tasks = capped_arguments.get("tasks")
    if isinstance(raw_tasks, list):
        capped_arguments["tasks"] = raw_tasks[:MAX_PARALLEL_AGENTS]
    return ParallelAgentPlan.model_validate(capped_arguments)


def format_parallel_agent_plan(plan: ParallelAgentPlan) -> str:
    return "\n".join(
        f"{index}. **{task.title}** — {task.instruction}"
        for index, task in enumerate(plan.tasks, start=1)
    )


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
