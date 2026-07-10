from __future__ import annotations

import json
import uuid
from typing import Any

import requests
from fastapi import HTTPException

from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# Z.AI Web Search MCP endpoint (streamable-http transport)
# Docs: https://docs.z.ai/devpack/mcp/search-mcp-server
GLM_MCP_ENDPOINT = "https://api.z.ai/api/mcp/web_search_prime/mcp"
GLM_REQUEST_TIMEOUT_SECONDS = 30

# MCP tool name discovered via tools/list
GLM_TOOL_NAME = "web_search_prime"


class RetryableGLMSearchError(Exception):
    """Error type used to trigger retry for transient GLM search failures."""


def _parse_sse_response(text: str) -> dict[str, Any]:
    """Parse an SSE response and return the JSON-RPC result event."""
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
            if isinstance(event, dict) and ("result" in event or "error" in event):
                return event
        except json.JSONDecodeError:
            continue

    raise ValueError(f"No JSON-RPC result in SSE response: {text[:300]}")


def _send_mcp_request(
    headers: dict[str, str],
    method: str,
    params: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Send an MCP JSON-RPC request. Returns (response_body, session_id)."""
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    # Notifications have no id; requests do
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params

    try:
        response = requests.post(
            GLM_MCP_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=GLM_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RetryableGLMSearchError(f"GLM request failed: {exc}") from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableGLMSearchError(
            f"GLM request failed (status {response.status_code}): "
            f"{response.text[:200]}"
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ValueError(
            f"GLM request failed (status {response.status_code}): "
            f"{response.text[:200]}"
        ) from exc

    # Extract session ID from response headers
    session_id = (
        response.headers.get("Mcp-Session-Id")
        or response.headers.get("mcp-session-id")
    )

    # Notifications don't expect a response body
    if request_id is None:
        return {}, session_id

    body = response.text.strip()
    if not body:
        raise ValueError(
            f"GLM returned empty response for method={method}"
        )

    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return _parse_sse_response(body), session_id

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"GLM returned non-JSON response: {body[:200]}"
        ) from exc

    # Detect non-JSON-RPC error responses (e.g. {"code": 401, "msg": "..."})
    if isinstance(data, dict) and "code" in data and not data.get("success", True):
        code = data.get("code", "unknown")
        msg = data.get("msg", str(data))
        if code in (401, 403):
            raise ValueError(f"GLM auth error ({code}): {msg}")
        raise RetryableGLMSearchError(f"GLM error ({code}): {msg}")

    return data, session_id


class GLMClient(WebSearchProvider):
    """Z.AI GLM web search client.

    Supports two transport modes:
      - "rest" (default): Uses the REST API at /api/coding/paas/v4/web_search.
        More reliable — the MCP endpoint has a known billing routing bug
        (see github.com/zai-org/GLM-5/issues/36).
      - "mcp": Uses the MCP streamable-http transport at
        /api/mcp/web_search_prime/mcp with full JSON-RPC lifecycle.
    """

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        transport: str = "rest",
    ) -> None:
        self._api_key = api_key
        self._num_results = min(num_results, 50)
        self._transport = transport
        self._base_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
        }
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        h = dict(self._base_headers)
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _initialize(self) -> None:
        """Perform the full MCP initialization handshake."""
        # Step 1: initialize request
        result, session_id = _send_mcp_request(
            self._headers(),
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "onyx", "version": "1.0.0"},
            },
            request_id=str(uuid.uuid4()),
        )
        if session_id:
            self._session_id = session_id

        # Check for init error
        if "error" in result:
            err = result["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise ValueError(f"GLM MCP initialize failed: {msg}")

        # Step 2: notifications/initialized (no id = notification)
        _send_mcp_request(
            self._headers(),
            method="notifications/initialized",
        )

        logger.debug(
            f"GLM MCP session initialized (session={self._session_id})"
        )

    def _ensure_session(self) -> None:
        if self._session_id is None:
            self._initialize()

    def _call_tool(self, query: str) -> dict[str, Any]:
        """Dispatch to REST or MCP transport based on config."""
        if self._transport == "mcp":
            return self._call_tool_mcp(query)
        return self._call_tool_rest(query)

    def _call_tool_mcp(self, query: str) -> dict[str, Any]:
        """Call web_search_prime via MCP streamable-http transport."""
        self._ensure_session()

        result, _ = _send_mcp_request(
            self._headers(),
            method="tools/call",
            params={
                "name": GLM_TOOL_NAME,
                "arguments": {
                    "search_query": query,
                },
            },
            request_id=str(uuid.uuid4()),
        )
        return result

    def _call_tool_rest(self, query: str) -> dict[str, Any]:
        """Call web search via REST API (more reliable than MCP).

        The MCP endpoint has a known billing routing bug that returns
        empty results (see github.com/zai-org/GLM-5/issues/36).
        The REST API at /api/coding/paas/v4/web_search works correctly.
        """
        try:
            response = requests.post(
                "https://api.z.ai/api/coding/paas/v4/web_search",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "web-search-pro",
                    "search_query": query,
                    "search_engine": "search-std",
                },
                timeout=GLM_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise RetryableGLMSearchError(f"GLM request failed: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableGLMSearchError(
                f"GLM request failed (status {response.status_code}): "
                f"{response.text[:200]}"
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ValueError(
                f"GLM request failed (status {response.status_code}): "
                f"{response.text[:200]}"
            ) from exc

        data = response.json()
        if "error" in data:
            code = data["error"].get("code", "")
            msg = data["error"].get("message", str(data["error"]))
            if str(code) == "1113":
                raise ValueError(
                    f"GLM insufficient balance: {msg}. "
                    "Add pay-as-you-go credit or check subscription."
                )
            raise ValueError(f"GLM API error ({code}): {msg}")

        # Wrap in JSON-RPC-like format for _parse_results compatibility
        return {
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(data.get("search_result", []))}
                ],
                "isError": False,
            }
        }

    @staticmethod
    def _parse_results(rpc_response: dict[str, Any]) -> list[WebSearchResult]:
        """Parse MCP JSON-RPC response into WebSearchResult list."""
        # JSON-RPC level error
        if "error" in rpc_response:
            error = rpc_response["error"]
            msg = (
                error.get("message", str(error))
                if isinstance(error, dict)
                else str(error)
            )
            raise ValueError(f"GLM MCP error: {msg}")

        # Non-JSON-RPC error (GLM returns {"code": 401, "msg": "..."})
        if "code" in rpc_response and not rpc_response.get("success", True):
            msg = rpc_response.get("msg", str(rpc_response))
            raise ValueError(f"GLM API error ({rpc_response['code']}): {msg}")

        result = rpc_response.get("result", {})

        # Tool-level error (isError flag in MCP content)
        if result.get("isError"):
            texts = [
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            ]
            raise ValueError(
                f"GLM search error: {' '.join(texts)}"
            )

        # Extract search results from content
        content_items = result.get("content", [])
        results: list[WebSearchResult] = []

        for item in content_items:
            if item.get("type") != "text":
                continue

            text = item.get("text", "")
            parsed = _unwrap_json(text)
            if parsed is None:
                continue

            entries = []
            if isinstance(parsed, list):
                entries = parsed
            elif isinstance(parsed, dict):
                # Might be a wrapper: {"search_result": [...]} or {"results": [...]}
                for key in ("search_result", "results", "items"):
                    if isinstance(parsed.get(key), list):
                        entries = parsed[key]
                        break
                if not entries:
                    entries = [parsed]

            for entry in entries:
                r = _extract_search_result(entry)
                if r:
                    results.append(r)

        if not results:
            logger.warning(
                "GLM web_search_prime returned 0 results. This may be caused "
                "by a known Z.AI billing bug where searches fail silently when "
                "using subscription quota with zero pay-as-you-go balance. "
                "See https://github.com/zai-org/GLM-5/issues/36"
            )

        return results

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableGLMSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        rpc_response = self._call_tool(query)
        return self._parse_results(rpc_response)

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableGLMSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            result = self._call_tool("test")

            # Check for errors in the wrapped response
            tool_result = result.get("result", {})
            if tool_result.get("isError"):
                texts = [
                    item.get("text", "")
                    for item in tool_result.get("content", [])
                    if item.get("type") == "text"
                ]
                error_text = " ".join(texts)
                raise ValueError(f"GLM search error: {error_text}")

        except HTTPException:
            raise
        except (ValueError, requests.RequestException) as e:
            error_msg = str(e)
            lower = error_msg.lower()
            if any(
                kw in lower
                for kw in (
                    "status 401", "status 403", "invalid",
                    "unauthorized", "api key not found", "apikey",
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid GLM API key: {error_msg}",
                ) from e
            if any(
                kw in lower
                for kw in (
                    "status 429", "rate limit", "insufficient balance",
                    "余额不足", "1113",
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"GLM API: {error_msg}",
                ) from e
            raise HTTPException(
                status_code=400,
                detail=f"GLM API key validation failed: {error_msg}",
            ) from e

        logger.info("Web search provider test succeeded for GLM.")
        return {"status": "ok"}


def _unwrap_json(text: str) -> Any:
    """Unwrap potentially double-encoded JSON strings.

    GLM returns text content as a JSON string that may itself contain
    another JSON string (e.g. ``"\"[{...}]\""``).  Unwrap until we
    reach a list or dict.
    """
    value: Any = text
    for _ in range(3):
        if isinstance(value, (list, dict)):
            return value
        if not isinstance(value, str):
            return None
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return value if isinstance(value, (list, dict)) else None


def _extract_search_result(entry: Any) -> WebSearchResult | None:
    """Extract a WebSearchResult from a dict-like entry."""
    if not isinstance(entry, dict):
        return None

    link = (entry.get("link") or entry.get("url") or "").strip()
    title = (entry.get("title") or entry.get("name") or "").strip()

    # REST API results may have empty link but valid content
    if not link and not title:
        return None

    snippet = (
        entry.get("content")
        or entry.get("snippet")
        or entry.get("summary")
        or entry.get("description")
        or ""
    ).strip()
    # Truncate very long snippets (REST API can return full articles)
    if len(snippet) > 500:
        snippet = snippet[:497] + "..."

    return WebSearchResult(
        title=title,
        link=link,
        snippet=snippet,
        author=entry.get("media"),
        published_date=entry.get("publish_date"),
    )
