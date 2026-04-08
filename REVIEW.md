# Review: disconnect/reconnect behavior for LiteLLM and Claude CLI providers

## Verdict

**Improved, but still not a fully faithful reconnect/live-resume experience.**

From code inspection, the system now:
- continues generation after disconnect
- can reconnect to an in-flight run
- keeps queueing packets during the disconnect window
- renders resumed packets live in the UI

But a reconnecting tab still does **not** reconstruct the partial assistant text that was already streamed **before** the disconnect. Until the final refetch happens, the resumed live view can therefore be incomplete.

## What is working

- **Generation continues after disconnect** for both LiteLLM-backed providers and Claude CLI because disconnect handling is above the provider layer in the shared background execution path: `backend/onyx/chat/process_message.py:947-1227`
- **Processing state cleanup is correct** and happens after persistence completes: `backend/onyx/chat/process_message.py:1211-1227`
- **Backend resume lookup is fixed**:
  - registry key normalization: `backend/onyx/chat/background_inference.py:58-99`
  - resume endpoint: `backend/onyx/server/query_and_chat/chat_backend.py:980-1023`
- **Backend now keeps queueing streamed packets** during disconnect instead of dropping them:
  - `backend/onyx/chat/process_message.py:1177-1179`
- **Frontend automatically attempts resume on reconnect** when the session reload shows the loading placeholder: `web/src/hooks/useChatSessionController.ts:268-283`
- **Frontend resume path renders resumed packets incrementally**:
  - resume entrypoint: `web/src/hooks/useChatController.ts:999-1160`
  - resumed text accumulation: `web/src/hooks/useChatController.ts:1059-1122`
  - resumed UI update: `web/src/hooks/useChatController.ts:1125-1147`

## Remaining issue

### Reconnect does not reconstruct the already-streamed prefix from before disconnect

Why:
- While the original tab is connected, it consumes packets from the shared queue as they are produced: `backend/onyx/chat/process_message.py:1283-1295`
- On reconnect, the loaded session does **not** contain the partial in-flight answer; instead the backend overwrites the last assistant message with the loading placeholder: `backend/onyx/server/query_and_chat/chat_backend.py:334-341`
- In `resumeStream(...)`, the resumed answer accumulator starts empty: `web/src/hooks/useChatController.ts:1059-1061`
- The resumed drain loop only rebuilds text from packets it receives during the resumed session: `web/src/hooks/useChatController.ts:1106-1122`

Consequence:
- Packets produced **after** disconnect are retained and can be shown live on reconnect
- But packets already consumed by the original connection **before** disconnect are gone from the queue
- Since the reconnecting tab only has the placeholder, its live resumed message can begin mid-answer until the final refetch replaces it with the fully persisted result

## Current behavior

- **Tab closes / disconnects:** generation continues in the backend.
- **User reconnects while generation is still running:** frontend automatically calls the resume path.
- **Packets generated during the disconnect gap:** retained and replayed.
- **Packets already streamed before disconnect:** not reconstructed into the reconnecting tab’s live message.
- **After generation finishes:** frontend refetches the session and shows the final persisted full answer/tool state.

## Why this matters

If the requirement is only:
- "the model should keep running and the user should eventually get the full answer after reconnect"

then the current implementation is close and mostly satisfies it.

If the requirement is stronger:
- "the reconnecting tab should continue showing the full in-progress answer exactly as if the stream had never been interrupted"

then the current implementation still does **not** satisfy it.

## How to fix it

To make reconnect fully faithful, the reconnecting tab needs a recoverable prefix for the already-streamed partial answer.

Concrete options:

1. **Keep a replay buffer from the start of the assistant stream**
   - Retain all assistant stream packets until completion, not just packets produced after disconnect
   - On reconnect, replay the full buffered stream into the UI, then continue live

2. **Store partial assistant state separately**
   - Persist or cache the current partial assistant text and any needed packet metadata while streaming
   - Return that partial state on session reload or from the resume endpoint
   - Initialize the reconnecting UI from that partial state before draining resumed packets

3. **Augment the resume endpoint**
   - Return a snapshot of the current partial answer plus the live stream tail
   - Then the frontend can set `answer` to the snapshot first and append resumed deltas after that

The simplest reliable approach is either:
- a bounded replay buffer containing the full stream so far, or
- cached partial assistant text returned alongside resume/session fetch.

## Bottom line

For the requirement that **LiteLLM and Claude CLI providers must continue working and responding if the user closes the tab/session/disconnects**, the current implementation is **good for continuation, reconnect, and eventual recovery**, but **not yet a fully faithful live resume**.

The remaining code-level gap is reconstruction of the already-streamed partial answer prefix for the reconnecting tab.

## Note

This review is based on code inspection of the current local changes. I did not run an end-to-end reconnect test in this review.