from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel
from typing_extensions import override

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple, LlmStepResult
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import (
    RESEARCH_AGENT_CONTEXT_KEY,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.deep_research.models import CombinedResearchAgentCallResult
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import ReasoningEffort, ToolChoiceOptions
from onyx.prompts.parallel_agents import (
    PARALLEL_AGENT_PLANNER_PROMPT,
    PARALLEL_AGENT_SYNTHESIS_PROMPT,
    PARALLEL_AGENT_SYNTHESIS_TASK,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    DeepResearchPlanDelta,
    DeepResearchPlanStart,
    IntermediateReportCitedDocs,
    IntermediateReportDelta,
    IntermediateReportStart,
    Packet,
    ResearchAgentStart,
    SectionEnd,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ToolCallException,
    ToolCallInfo,
    ToolCallKickoff,
    ToolResponse,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.parallel_agents.models import (
    MAX_PARALLEL_AGENTS,
    ParallelAgentPlan,
    build_parallel_agent_execution_batches,
    build_parallel_agent_search_response,
    format_parallel_agent_plan,
    parse_parallel_agent_plan,
    truncate_text_to_token_budget,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

logger = setup_logger()

PARALLEL_AGENT_TASK_KEY = "task"
SUBMIT_PARALLEL_PLAN_TOOL_NAME = "submit_parallel_plan"
MAX_SYNTHESIS_OUTPUT_TOKENS = 10000
SYNTHESIS_INPUT_BUDGET_RATIO = 0.8
DEPENDENCY_CONTEXT_BUDGET_RATIO = 0.4
PARALLEL_AGENT_EXECUTION_TIMEOUT_SECONDS = 35 * 60 * MAX_PARALLEL_AGENTS
PARALLEL_AGENT_DEPENDENCIES_KEY = "depends_on"


class ParallelAgentToolOverrideKwargs(BaseModel):
    parent_tool_call_id: str
    message_history: list[ChatMessageSimple]


def filter_parallel_agent_worker_tools(tools: list[Tool]) -> list[Tool]:
    """Keep tools whose operations are safe to repeat concurrently."""
    safe_tool_types = (SearchTool, WebSearchTool, OpenURLTool, FileReaderTool)
    return [tool for tool in tools if isinstance(tool, safe_tool_types)]


class ParallelAgentTool(Tool[ParallelAgentToolOverrideKwargs]):
    NAME = "parallel_agents"
    DISPLAY_NAME = "Parallel Agents"
    DESCRIPTION = (
        "Split a complex objective into up to five read-only worker tasks. Run "
        "independent tasks in parallel and dependent tasks sequentially, then "
        "synthesize their reports. Pass the complete delegated objective. Call this "
        "tool alone."
    )

    def __init__(
        self,
        tool_id: int,
        worker_tool_id: int,
        emitter: Emitter,
        llm: LLM,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._worker_tool_id = worker_tool_id
        self._llm = llm
        self._state_container: ChatStateContainer | None = None
        self._worker_tools: list[Tool] = []
        self._user_identity: LLMUserIdentity | None = None
        self._reasoning_effort = ReasoningEffort.AUTO
        self._agent_instructions = ""

    def configure_runtime(
        self,
        *,
        state_container: ChatStateContainer,
        tools: list[Tool],
        user_identity: LLMUserIdentity | None,
        reasoning_effort: ReasoningEffort,
        agent_instructions: str | None,
    ) -> None:
        self._state_container = state_container
        self._worker_tools = filter_parallel_agent_worker_tools(tools)
        self._user_identity = user_identity
        self._reasoning_effort = reasoning_effort
        self._agent_instructions = agent_instructions or ""

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def execution_timeout_seconds(self) -> float:
        return PARALLEL_AGENT_EXECUTION_TIMEOUT_SECONDS

    @override
    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        PARALLEL_AGENT_TASK_KEY: {
                            "type": "string",
                            "description": (
                                "The complete objective and all constraints that the "
                                "planner and workers must preserve."
                            ),
                        }
                    },
                    "required": [PARALLEL_AGENT_TASK_KEY],
                },
            },
        }

    @override
    def emit_start(self, placement: Placement) -> None:
        # The planner decides the branch count. Emit the start after planning so
        # TopLevelBranching remains the first packet for this turn.
        return

    def _raise_if_cancelled(self) -> None:
        if self.emitter.is_cancelled():
            raise ToolCallException(
                message="Parallel agent run cancelled",
                llm_facing_message="The parallel agent run was cancelled.",
            )

    def _consume_llm_generator(
        self,
        generator: Any,
    ) -> tuple[LlmStepResult, bool]:
        while True:
            self._raise_if_cancelled()
            try:
                next(generator)
            except StopIteration as stop:
                return cast(tuple[LlmStepResult, bool], stop.value)

    def _create_plan(
        self,
        delegated_objective: str,
        original_request: str,
        placement: Placement,
        token_counter: Callable[[str], int],
    ) -> ParallelAgentPlan:
        from onyx.chat.llm_step import run_llm_step_pkt_generator

        planner_sections = []
        if self._agent_instructions:
            planner_sections.append("Agent instructions:\n" + self._agent_instructions)
        planner_sections.append("Original user request:\n" + original_request)
        if delegated_objective not in original_request:
            planner_sections.append("Delegated objective:\n" + delegated_objective)
        planner_request = "\n\n".join(planner_sections)
        history = [
            ChatMessageSimple(
                message=PARALLEL_AGENT_PLANNER_PROMPT,
                token_count=token_counter(PARALLEL_AGENT_PLANNER_PROMPT),
                message_type=MessageType.SYSTEM,
            ),
            ChatMessageSimple(
                message=planner_request,
                token_count=token_counter(planner_request),
                message_type=MessageType.USER,
            ),
        ]
        plan_definition = {
            "type": "function",
            "function": {
                "name": SUBMIT_PARALLEL_PLAN_TOOL_NAME,
                "description": "Submit the worker execution plan.",
                "parameters": ParallelAgentPlan.model_json_schema(),
            },
        }

        with function_span("parallel_agent_planning") as span:
            span.span_data.input = delegated_objective
            generator = run_llm_step_pkt_generator(
                history=history,
                tool_definitions=[plan_definition],
                tool_choice=ToolChoiceOptions.REQUIRED,
                llm=self._llm,
                placement=placement,
                state_container=None,
                citation_processor=None,
                reasoning_effort=self._reasoning_effort,
                user_identity=self._user_identity,
                max_tokens=2000,
                use_existing_tab_index=True,
                is_deep_research=True,
                flow=LLMFlow.PARALLEL_AGENT_PLANNING,
            )
            result, _ = self._consume_llm_generator(generator)

            matching_call = next(
                (
                    call
                    for call in result.tool_calls or []
                    if call.tool_name == SUBMIT_PARALLEL_PLAN_TOOL_NAME
                ),
                None,
            )
            if matching_call is None:
                raise ToolCallException(
                    message="Planner did not submit a plan",
                    llm_facing_message="The parallel planner failed to create a plan.",
                )

            plan = parse_parallel_agent_plan(matching_call.tool_args)
            span.span_data.output = plan.model_dump()
            return plan

    def _build_synthesis_history(
        self,
        *,
        original_request: str,
        agent_instructions: str,
        delegated_objective: str,
        plan_text: str,
        plan: ParallelAgentPlan,
        reports: list[str | None],
        token_counter: Callable[[str], int],
    ) -> list[ChatMessageSimple]:
        total_budget = max(
            1000,
            int(self._llm.config.max_input_tokens * SYNTHESIS_INPUT_BUDGET_RATIO),
        )
        system_tokens = token_counter(PARALLEL_AGENT_SYNTHESIS_PROMPT)
        content_budget = max(500, total_budget - system_tokens)

        instruction_budget = max(100, content_budget // 5)
        original_budget = max(100, content_budget // 5)
        objective_budget = max(100, content_budget // 10)
        plan_budget = max(100, content_budget // 10)
        report_budget = max(
            100,
            (
                content_budget
                - instruction_budget
                - original_budget
                - objective_budget
                - plan_budget
            )
            // len(plan.tasks),
        )

        rendered_reports = []
        for index, task in enumerate(plan.tasks):
            report = reports[index] if index < len(reports) else None
            report_text = report or "Worker did not produce a report."
            rendered_reports.append(
                f"## {index + 1}. {task.title}\n"
                + truncate_text_to_token_budget(
                    report_text,
                    report_budget,
                    token_counter,
                )
            )

        synthesis_request = PARALLEL_AGENT_SYNTHESIS_TASK.format(
            agent_instructions=truncate_text_to_token_budget(
                agent_instructions,
                instruction_budget,
                token_counter,
            ),
            original_request=truncate_text_to_token_budget(
                original_request,
                original_budget,
                token_counter,
            ),
            delegated_objective=truncate_text_to_token_budget(
                delegated_objective,
                objective_budget,
                token_counter,
            ),
            plan=truncate_text_to_token_budget(
                plan_text,
                plan_budget,
                token_counter,
            ),
            worker_reports="\n\n".join(rendered_reports),
        )

        return [
            ChatMessageSimple(
                message=PARALLEL_AGENT_SYNTHESIS_PROMPT,
                token_count=system_tokens,
                message_type=MessageType.SYSTEM,
            ),
            ChatMessageSimple(
                message=synthesis_request,
                token_count=token_counter(synthesis_request),
                message_type=MessageType.USER,
            ),
        ]

    def _build_dependency_context(
        self,
        *,
        plan: ParallelAgentPlan,
        task_index: int,
        reports: list[str | None],
        token_counter: Callable[[str], int],
    ) -> str | None:
        dependencies = plan.tasks[task_index].depends_on
        if not dependencies:
            return None

        total_budget = max(
            500,
            int(self._llm.config.max_input_tokens * DEPENDENCY_CONTEXT_BUDGET_RATIO),
        )
        report_budget = max(100, total_budget // len(dependencies))
        dependency_reports = []
        for dependency in dependencies:
            dependency_task = plan.tasks[dependency - 1]
            report = reports[dependency - 1] or "Worker did not produce a report."
            dependency_reports.append(
                f"## Task {dependency}: {dependency_task.title}\n"
                + truncate_text_to_token_budget(
                    report,
                    report_budget,
                    token_counter,
                )
            )
        return "\n\n".join(dependency_reports)

    def _run_worker_plan(
        self,
        *,
        plan: ParallelAgentPlan,
        worker_calls: list[ToolCallKickoff],
        token_counter: Callable[[str], int],
    ) -> CombinedResearchAgentCallResult:
        from onyx.tools.fake_tools.research_agent import run_research_agent_calls

        if self._state_container is None:
            raise RuntimeError("ParallelAgentTool runtime was not configured")

        reports: list[str | None] = [None] * len(plan.tasks)
        citation_mapping = self._state_container.get_citation_to_doc()
        reasoning_effort = (
            self._reasoning_effort
            if self._reasoning_effort is not ReasoningEffort.AUTO
            else ReasoningEffort.LOW
        )
        is_reasoning_model = model_is_reasoning_model(
            self._llm.config.model_name,
            self._llm.config.model_provider,
        )

        for task_indexes in build_parallel_agent_execution_batches(plan):
            self._raise_if_cancelled()
            runtime_calls = []
            for task_index in task_indexes:
                call = worker_calls[task_index]
                runtime_arguments = dict(call.tool_args)
                dependency_context = self._build_dependency_context(
                    plan=plan,
                    task_index=task_index,
                    reports=reports,
                    token_counter=token_counter,
                )
                if dependency_context:
                    runtime_arguments[RESEARCH_AGENT_CONTEXT_KEY] = dependency_context
                runtime_calls.append(
                    call.model_copy(update={"tool_args": runtime_arguments})
                )

            batch_results = run_research_agent_calls(
                research_agent_calls=runtime_calls,
                parent_tool_call_ids=[call.tool_call_id for call in runtime_calls],
                tools=self._worker_tools,
                emitter=self.emitter,
                state_container=self._state_container,
                llm=self._llm,
                is_reasoning_model=is_reasoning_model,
                token_counter=token_counter,
                citation_mapping=citation_mapping,
                user_identity=self._user_identity,
                reasoning_effort=reasoning_effort,
                cancellation_check=self.emitter.is_cancelled,
                llm_flow=LLMFlow.PARALLEL_AGENT_WORKER,
            )
            for result_index, task_index in enumerate(task_indexes):
                reports[task_index] = batch_results.intermediate_reports[result_index]
            citation_mapping = batch_results.citation_mapping

        return CombinedResearchAgentCallResult(
            intermediate_reports=reports,
            citation_mapping=citation_mapping,
        )

    def _synthesize(
        self,
        *,
        original_request: str,
        delegated_objective: str,
        plan: ParallelAgentPlan,
        reports: list[str | None],
        citation_mapping: CitationMapping,
        placement: Placement,
        token_counter: Callable[[str], int],
    ) -> tuple[str, CitationMapping]:
        from onyx.chat.llm_step import run_llm_step_pkt_generator

        plan_text = format_parallel_agent_plan(plan)
        synthesis_history = self._build_synthesis_history(
            original_request=original_request,
            agent_instructions=self._agent_instructions,
            delegated_objective=delegated_objective,
            plan_text=plan_text,
            plan=plan,
            reports=reports,
            token_counter=token_counter,
        )
        citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        citation_processor.update_citation_mapping(citation_mapping)

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=ResearchAgentStart(
                    research_task="Synthesize all worker reports into one result."
                ),
            )
        )

        with function_span("parallel_agent_synthesis") as span:
            span.span_data.input = f"worker_reports={len(reports)}"
            generator = run_llm_step_pkt_generator(
                history=synthesis_history,
                tool_definitions=[],
                tool_choice=ToolChoiceOptions.NONE,
                llm=self._llm,
                placement=placement,
                state_container=None,
                citation_processor=citation_processor,
                reasoning_effort=self._reasoning_effort,
                final_documents=list(citation_mapping.values()),
                user_identity=self._user_identity,
                max_tokens=MAX_SYNTHESIS_OUTPUT_TOKENS,
                use_existing_tab_index=True,
                is_deep_research=True,
                flow=LLMFlow.PARALLEL_AGENT_SYNTHESIS,
            )

            while True:
                self._raise_if_cancelled()
                try:
                    packet = next(generator)
                except StopIteration as stop:
                    result, _ = cast(tuple[LlmStepResult, bool], stop.value)
                    break

                if isinstance(packet.obj, AgentResponseStart):
                    self.emitter.emit(
                        Packet(placement=placement, obj=IntermediateReportStart())
                    )
                elif isinstance(packet.obj, AgentResponseDelta):
                    self.emitter.emit(
                        Packet(
                            placement=placement,
                            obj=IntermediateReportDelta(content=packet.obj.content),
                        )
                    )

            answer = result.answer
            if not answer:
                raise ToolCallException(
                    message="Synthesizer returned no answer",
                    llm_facing_message=(
                        "The parallel agents completed, but synthesis failed."
                    ),
                )

            cited_mapping = citation_processor.get_seen_citations()
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=IntermediateReportCitedDocs(
                        cited_docs=list(cited_mapping.values())
                    ),
                )
            )
            self.emitter.emit(Packet(placement=placement, obj=SectionEnd()))
            span.span_data.output = answer
            return answer, cited_mapping

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: ParallelAgentToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if self._state_container is None:
            raise RuntimeError("ParallelAgentTool runtime was not configured")
        delegated_objective = cast(
            str | None,
            llm_kwargs.get(PARALLEL_AGENT_TASK_KEY),
        )
        if not delegated_objective or not delegated_objective.strip():
            raise ToolCallException(
                message="Parallel agent objective is missing",
                llm_facing_message=(
                    f"The {self.name} tool requires a '{PARALLEL_AGENT_TASK_KEY}'."
                ),
            )
        delegated_objective = delegated_objective.strip()

        original_request = next(
            (
                message.message
                for message in reversed(override_kwargs.message_history)
                if message.message_type == MessageType.USER
            ),
            delegated_objective,
        )
        token_counter = get_llm_token_counter(self._llm)
        self._raise_if_cancelled()

        plan = self._create_plan(
            delegated_objective=delegated_objective,
            original_request=original_request,
            placement=placement,
            token_counter=token_counter,
        )
        plan_text = format_parallel_agent_plan(plan)
        branch_count = len(plan.tasks) + 2
        self.emitter.emit(
            Packet(
                placement=Placement(turn_index=placement.turn_index),
                obj=TopLevelBranching(num_parallel_branches=branch_count),
            )
        )
        self.emitter.emit(Packet(placement=placement, obj=DeepResearchPlanStart()))
        self.emitter.emit(
            Packet(placement=placement, obj=DeepResearchPlanDelta(content=plan_text))
        )
        self.emitter.emit(Packet(placement=placement, obj=SectionEnd()))

        base_tab_index = placement.tab_index
        worker_calls = [
            ToolCallKickoff(
                tool_call_id=str(uuid4()),
                tool_name=RESEARCH_AGENT_TOOL_NAME,
                tool_args={
                    RESEARCH_AGENT_TASK_KEY: task.instruction,
                    "title": task.title,
                    PARALLEL_AGENT_DEPENDENCIES_KEY: task.depends_on,
                },
                placement=Placement(
                    turn_index=placement.turn_index,
                    tab_index=base_tab_index + index,
                ),
            )
            for index, task in enumerate(plan.tasks, start=1)
        ]

        worker_results = self._run_worker_plan(
            plan=plan,
            worker_calls=worker_calls,
            token_counter=token_counter,
        )
        self._raise_if_cancelled()

        for index, call in enumerate(worker_calls):
            report = worker_results.intermediate_reports[index]
            self._state_container.add_tool_call(
                ToolCallInfo(
                    parent_tool_call_id=override_kwargs.parent_tool_call_id,
                    turn_index=0,
                    tab_index=call.placement.tab_index,
                    tool_name=call.tool_name,
                    tool_call_id=call.tool_call_id,
                    tool_id=self._worker_tool_id,
                    reasoning_tokens=None,
                    tool_call_arguments=call.tool_args,
                    tool_call_response=(report or "Worker did not produce a report."),
                )
            )

        synthesis_placement = Placement(
            turn_index=placement.turn_index,
            tab_index=base_tab_index + len(plan.tasks) + 1,
        )
        answer, cited_mapping = self._synthesize(
            original_request=original_request,
            delegated_objective=delegated_objective,
            plan=plan,
            reports=worker_results.intermediate_reports,
            citation_mapping=worker_results.citation_mapping,
            placement=synthesis_placement,
            token_counter=token_counter,
        )

        return ToolResponse(
            rich_response=build_parallel_agent_search_response(
                citation_mapping=worker_results.citation_mapping,
                cited_mapping=cited_mapping,
            ),
            llm_facing_response=answer,
        )
