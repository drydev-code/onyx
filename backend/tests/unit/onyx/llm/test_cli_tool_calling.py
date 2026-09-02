from onyx.llm.cli_tool_calling import (
    append_cli_tool_instructions,
    parse_cli_tool_calls,
)
from onyx.llm.models import NamedToolChoice, ToolChoiceOptions

PARALLEL_TOOL = {
    "type": "function",
    "function": {
        "name": "parallel_agents",
        "description": "Run independent workers.",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
    },
}


def test_parallel_agents_uses_onyx_xml_tool_protocol() -> None:
    prompt = append_cli_tool_instructions(
        "Research this.",
        [PARALLEL_TOOL],
        ToolChoiceOptions.AUTO,
    )

    assert "<onyx-tool-protocol>" in prompt
    assert '"name":"parallel_agents"' in prompt
    assert '<invoke name="TOOL_NAME">' in prompt
    assert "Do not replace it with a CLI-native agent" in prompt
    assert "Otherwise, answer normally" in prompt


def test_required_and_named_tool_choices_are_explicit() -> None:
    required = append_cli_tool_instructions(
        "Plan.",
        [PARALLEL_TOOL],
        ToolChoiceOptions.REQUIRED,
    )
    named = append_cli_tool_instructions(
        "Plan.",
        [PARALLEL_TOOL],
        NamedToolChoice(name="parallel_agents"),
    )

    assert "must call one available Onyx tool" in required
    assert "must call the 'parallel_agents' tool and no other tool" in named


def test_tool_protocol_is_omitted_when_tools_are_disabled() -> None:
    assert (
        append_cli_tool_instructions(
            "Answer directly.",
            [PARALLEL_TOOL],
            ToolChoiceOptions.NONE,
        )
        == "Answer directly."
    )


def test_parses_advertised_parallel_agents_call() -> None:
    calls = parse_cli_tool_calls(
        '<function_calls><invoke name="parallel_agents">'
        '<parameter name="task" string="true">Compare A &amp; B.</parameter>'
        "</invoke></function_calls>",
        [PARALLEL_TOOL],
    )

    assert len(calls) == 1
    assert calls[0].name == "parallel_agents"
    assert calls[0].arguments == {"task": "Compare A & B."}


def test_rejects_unadvertised_cli_tool_call() -> None:
    calls = parse_cli_tool_calls(
        '<function_calls><invoke name="unknown"></invoke></function_calls>',
        [PARALLEL_TOOL],
    )

    assert calls == []


def test_parses_json_fallback_for_required_tool_calls() -> None:
    calls = parse_cli_tool_calls(
        '{"name":"parallel_agents","arguments":{"task":"Compare A and B."}}',
        [PARALLEL_TOOL],
    )

    assert len(calls) == 1
    assert calls[0].arguments == {"task": "Compare A and B."}
