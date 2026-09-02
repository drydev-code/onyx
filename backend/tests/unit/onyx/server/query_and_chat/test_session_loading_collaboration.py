import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    CollaborationEvent,
    ReasoningDelta,
    StreamingType,
)


def test_translate_assistant_message_restores_collaboration_output() -> None:
    receiver_id = "child-thread-1"
    chat_message = cast(
        ChatMessage,
        SimpleNamespace(
            id=42,
            message_type=MessageType.ASSISTANT,
            tool_calls=[],
            collaboration_events=[
                {
                    "item_id": "item_0",
                    "phase": "completed",
                    "tool": "wait",
                    "sender_thread_id": "parent-thread",
                    "receiver_thread_ids": [receiver_id],
                    "prompt": None,
                    "agents_states": {
                        receiver_id: {
                            "status": "completed",
                            "message": "Saved agent report.",
                        }
                    },
                    "status": "completed",
                }
            ],
            citations=None,
            reasoning_tokens=None,
            message="Final answer.",
            search_docs=[],
        ),
    )

    packets = translate_assistant_message_to_packets(
        chat_message=chat_message,
        db_session=MagicMock(),
    )

    collaboration_packet = next(
        packet
        for packet in packets
        if packet.obj.type == StreamingType.COLLABORATION_EVENT.value
    )
    event = cast(CollaborationEvent, collaboration_packet.obj)
    message_packet = next(
        packet
        for packet in packets
        if packet.obj.type == StreamingType.MESSAGE_START.value
    )

    assert event.agents_states[receiver_id].message == "Saved agent report."
    assert message_packet.placement.turn_index > (
        collaboration_packet.placement.turn_index
    )


def test_translate_assistant_message_converts_legacy_collaboration_block() -> None:
    receiver_id = "child-thread-1"
    legacy_payload = {
        "id": "item_0",
        "type": "collab_tool_call",
        "tool": "wait",
        "sender_thread_id": "parent-thread",
        "receiver_thread_ids": [receiver_id],
        "prompt": None,
        "agents_states": {
            receiver_id: {
                "status": "completed",
                "message": "Legacy agent report.",
            }
        },
        "status": "completed",
    }
    legacy_reasoning = (
        "Visible reasoning.\n\n---\n\n### 🔧 `collab_tool_call`\n\n"
        f"```json\n{json.dumps(legacy_payload, indent=2)}\n```\n"
    )
    chat_message = cast(
        ChatMessage,
        SimpleNamespace(
            id=43,
            message_type=MessageType.ASSISTANT,
            tool_calls=[],
            collaboration_events=None,
            citations=None,
            reasoning_tokens=legacy_reasoning,
            message="Final answer.",
            search_docs=[],
        ),
    )

    packets = translate_assistant_message_to_packets(
        chat_message=chat_message,
        db_session=MagicMock(),
    )

    event = cast(
        CollaborationEvent,
        next(
            packet.obj
            for packet in packets
            if packet.obj.type == StreamingType.COLLABORATION_EVENT.value
        ),
    )
    reasoning = cast(
        ReasoningDelta,
        next(
            packet.obj
            for packet in packets
            if packet.obj.type == StreamingType.REASONING_DELTA.value
        ),
    )

    assert event.phase == "completed"
    assert event.agents_states[receiver_id].message == "Legacy agent report."
    assert reasoning.reasoning == "Visible reasoning."
