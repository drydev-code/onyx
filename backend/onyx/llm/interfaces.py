import abc
from collections.abc import Iterator

from braintrust import traced
from pydantic import BaseModel

from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.utils.logger import setup_logger

logger = setup_logger()


class LLMUserIdentity(BaseModel):
    user_id: str | None = None
    session_id: str | None = None


class LLMConfig(BaseModel):
    model_provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None
    custom_config: dict[str, str] | None = None
    max_input_tokens: int
    # Map from provider-native tool name -> bridge category. When set, a
    # provider declares that it self-executes certain tools internally
    # (e.g. Claude Code CLI runs tools inside the CLI binary via MCP).
    # llm_step.py routes matching tool_calls to the CLI bridge helper for
    # direct UI packet emission and skips the normal kickoff/execution
    # path for those tools. Leave None for standard LiteLLM providers.
    cli_tool_bridge: dict[str, str] | None = None
    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class LLM(abc.ABC):
    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        raise NotImplementedError

    @traced(name="invoke llm", type="llm")
    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> "ModelResponse":
        raise NotImplementedError

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise NotImplementedError
