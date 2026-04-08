"""Background inference registry.

Tracks LLM inference jobs that run independently of the HTTP connection.
When a user sends a chat message, the LLM workers are launched in a background
thread. Stream items are appended to a shared history; if the client
disconnects, the background thread continues to completion and persists the
result to the DB.

The registry allows a reconnecting client to attach to a still-running
inference or discover that it has already completed.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from onyx.utils.logger import setup_logger

logger = setup_logger()

# How long a completed entry stays in the registry before being evicted.
_COMPLETED_TTL_SECONDS = 600  # 10 minutes


@dataclass
class BackgroundInference:
    """State for a single background inference run."""

    # Immutable-by-convention stream history.
    #
    # Every streamed ``Packet`` / ``StreamingError`` is appended here so a
    # reconnecting client can replay the full in-flight response from the
    # beginning instead of only seeing packets produced after disconnect.
    packet_history: list[Any] = field(default_factory=list)

    # Condition variable guarding ``packet_history``. Writers notify when new
    # packets arrive or when the run completes so waiting consumers wake up.
    packet_condition: threading.Condition = field(default_factory=threading.Condition)

    # Set when the background thread has finished *all* work (including DB saves).
    done: threading.Event = field(default_factory=threading.Event)

    # Set by the SSE consumer when the client disconnects. The background
    # thread keeps running and appending packets so a reconnecting client can
    # replay the full history and then continue live.
    client_disconnected: threading.Event = field(default_factory=threading.Event)

    # Reference to the background thread (for debugging / join in tests).
    thread: threading.Thread | None = None

    # Timestamp when ``done`` was set — used for TTL eviction.
    completed_at: float | None = None


# ── Module-level registry ─────────────────────────────────────────────────────

_registry: dict[str, BackgroundInference] = {}
_registry_lock = threading.Lock()


def _make_key(chat_session_id: object, message_id: object) -> str:
    """Registry key scoped to a specific assistant message.

    Accepts any type (UUID, int, str) and coerces to string so that
    registration and lookup use the same representation.
    """
    return f"{chat_session_id}:{message_id}"


def register(chat_session_id: object, message_id: object) -> BackgroundInference:
    """Create and register a new background inference entry.

    Returns the ``BackgroundInference`` handle that callers use to interact
    with the running job.
    """
    key = _make_key(chat_session_id, message_id)
    entry = BackgroundInference()
    with _registry_lock:
        _evict_stale_locked()
        _registry[key] = entry
    return entry


def lookup(chat_session_id: object, message_id: object) -> BackgroundInference | None:
    """Look up an active or recently-completed inference."""
    key = _make_key(chat_session_id, message_id)
    with _registry_lock:
        return _registry.get(key)


def lookup_by_session(chat_session_id: object) -> BackgroundInference | None:
    """Find an active (not yet completed) inference for a chat session.

    Returns the first entry whose key starts with ``chat_session_id:``
    and whose ``done`` event is not yet set, or ``None``.
    """
    prefix = f"{chat_session_id}:"
    with _registry_lock:
        for key, entry in _registry.items():
            if key.startswith(prefix) and not entry.done.is_set():
                return entry
    return None


def unregister(chat_session_id: object, message_id: object) -> None:
    """Remove an entry from the registry (e.g. after TTL or explicit cleanup)."""
    key = _make_key(chat_session_id, message_id)
    with _registry_lock:
        _registry.pop(key, None)


def append_packet(entry: BackgroundInference, item: Any) -> None:
    """Append a streamed item and wake any waiting consumers."""
    with entry.packet_condition:
        entry.packet_history.append(item)
        entry.packet_condition.notify_all()


def wait_for_packet(
    entry: BackgroundInference,
    next_index: int,
    timeout: float | None = None,
) -> tuple[Any | None, int]:
    """Return the next packet for a consumer cursor.

    Consumers keep their own ``next_index`` cursor. If the requested packet is
    not available yet, this blocks up to ``timeout`` waiting for either a new
    packet or completion.
    """
    with entry.packet_condition:
        if next_index >= len(entry.packet_history) and not entry.done.is_set():
            entry.packet_condition.wait(timeout=timeout)

        if next_index < len(entry.packet_history):
            return entry.packet_history[next_index], next_index + 1

        return None, next_index


def mark_done(entry: BackgroundInference) -> None:
    """Signal that the background thread has finished all work."""
    with entry.packet_condition:
        entry.completed_at = time.monotonic()
        entry.done.set()
        entry.packet_condition.notify_all()


def _evict_stale_locked() -> None:
    """Remove entries that completed more than ``_COMPLETED_TTL_SECONDS`` ago.

    Must be called while holding ``_registry_lock``.
    """
    now = time.monotonic()
    stale_keys = [
        k
        for k, v in _registry.items()
        if v.completed_at is not None
        and (now - v.completed_at) > _COMPLETED_TTL_SECONDS
    ]
    for k in stale_keys:
        del _registry[k]
