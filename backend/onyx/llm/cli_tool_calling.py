"""Prompt protocol for Onyx tool calls from CLI-backed providers."""

import json
import re
from html import unescape
from typing import NamedTuple

from onyx.llm.models import NamedToolChoice, ToolChoice, ToolChoiceOptions
from onyx.utils.postgres_sanitization import sanitize_string
from onyx.utils.text_processing import find_all_json_objects

_INVOKE_RE = re.compile(
    r"<invoke\b(?P<attrs>[^>]*)>(?P<body>.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_RE = re.compile(
    r"<parameter\b(?P<attrs>[^>]*)>(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)


class ParsedCLIToolCall(NamedTuple):
    name: str
    arguments: dict[str, object]


def _xml_attribute(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1",
        attrs,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sanitize_string(unescape(match.group(2).strip())) if match else None


def parse_cli_tool_calls(
    response_text: str,
    tools: list[dict] | None,
) -> list[ParsedCLIToolCall]:
    """Parse CLI-emitted XML calls and accept only advertised Onyx tools."""
    if not response_text or not tools:
        return []

    available_names = {
        str(function["name"])
        for tool in tools
        if isinstance((function := tool.get("function")), dict) and function.get("name")
    }
    calls: list[ParsedCLIToolCall] = []
    for invoke_match in _INVOKE_RE.finditer(response_text):
        tool_name = _xml_attribute(invoke_match.group("attrs"), "name")
        if not tool_name or tool_name not in available_names:
            continue

        arguments: dict[str, object] = {}
        for parameter_match in _PARAMETER_RE.finditer(invoke_match.group("body")):
            parameter_name = _xml_attribute(parameter_match.group("attrs"), "name")
            if not parameter_name:
                continue
            string_attr = _xml_attribute(parameter_match.group("attrs"), "string")
            value = sanitize_string(unescape(parameter_match.group("value").strip()))
            if string_attr and string_attr.casefold() == "true":
                arguments[parameter_name] = value
                continue
            try:
                arguments[parameter_name] = json.loads(value)
            except json.JSONDecodeError:
                arguments[parameter_name] = value

        calls.append(ParsedCLIToolCall(name=tool_name, arguments=arguments))

    if calls:
        return calls

    for candidate in find_all_json_objects(response_text):
        tool_name = candidate.get("name")
        arguments = candidate.get("arguments", candidate.get("parameters"))
        if tool_name not in available_names or not isinstance(arguments, dict):
            continue
        calls.append(
            ParsedCLIToolCall(
                name=str(tool_name),
                arguments={str(key): value for key, value in arguments.items()},
            )
        )
    return calls


def append_cli_tool_instructions(
    prompt_text: str,
    tools: list[dict] | None,
    tool_choice: ToolChoice | None,
) -> str:
    """Describe Onyx tools using the XML format parsed by the chat loop."""
    if not tools or tool_choice == ToolChoiceOptions.NONE:
        return prompt_text

    if isinstance(tool_choice, NamedToolChoice):
        selection_instruction = (
            f"You must call the '{tool_choice.name}' tool and no other tool."
        )
    elif tool_choice == ToolChoiceOptions.REQUIRED:
        selection_instruction = "You must call one available Onyx tool."
    else:
        selection_instruction = (
            "Call an Onyx tool when it is useful. Otherwise, answer normally."
        )

    parallel_instruction = ""
    tool_names = {
        function.get("name")
        for tool in tools
        if isinstance((function := tool.get("function")), dict)
    }
    if "parallel_agents" in tool_names:
        parallel_instruction = (
            "When you delegate with parallel_agents, call the Onyx tool below. "
            "Do not replace it with a CLI-native agent or subagent tool.\n"
        )

    definitions = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    protocol = (
        "<onyx-tool-protocol>\n"
        "The following tools run in Onyx after your response. Do not execute or "
        "simulate them inside the CLI.\n"
        f"{selection_instruction}\n"
        f"{parallel_instruction}"
        "To call a tool, output only this XML structure:\n"
        '<function_calls><invoke name="TOOL_NAME">'
        '<parameter name="STRING_ARGUMENT" string="true">value</parameter>'
        '<parameter name="JSON_ARGUMENT" string="false">'
        "valid JSON value</parameter></invoke></function_calls>\n"
        'Use one parameter element for each argument. Use string="false" for '
        "arrays, objects, numbers, booleans, and null.\n"
        "XML-escape ampersands and angle brackets inside parameter values.\n"
        f"<tool-definitions>{definitions}</tool-definitions>\n"
        "</onyx-tool-protocol>"
    )
    return f"{prompt_text}\n\n{protocol}"
