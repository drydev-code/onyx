#!/usr/bin/env python3
"""Isolated test for Z.AI web_search_prime MCP server.

Tests the full MCP lifecycle: initialize → tools/list → tools/call
with detailed logging of every request/response.

Usage:
  python test_glm_mcp.py <api_key>
  python test_glm_mcp.py <api_key> "search query"
"""
import json
import sys
import uuid

import requests

ENDPOINT = "https://api.z.ai/api/mcp/web_search_prime/mcp"
TIMEOUT = 30


def log(msg):
    print(f"  {msg}", flush=True)


def send(headers, method, params=None, req_id=None):
    """Send MCP JSON-RPC request, return parsed response + session_id."""
    payload = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        payload["id"] = req_id
    if params is not None:
        payload["params"] = params

    print(f"\n→ {method}", flush=True)
    log(f"Payload: {json.dumps(payload)[:200]}")

    r = requests.post(ENDPOINT, headers=headers, json=payload, timeout=TIMEOUT)
    log(f"HTTP {r.status_code} {r.headers.get('content-type', '?')}")

    sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
    if sid:
        log(f"Session-Id: {sid}")

    # Notifications (no id) don't expect body
    if req_id is None:
        return {}, sid

    body = r.text.strip()
    log(f"Raw body ({len(body)} chars): {body[:500]}")

    ct = r.headers.get("content-type", "")

    # Parse SSE
    if "text/event-stream" in ct:
        for line in body.splitlines():
            if line.startswith("data:"):
                raw = line[len("data:"):].strip()
                if raw:
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict) and ("result" in data or "error" in data):
                            return data, sid
                    except json.JSONDecodeError:
                        pass
        log("WARNING: No JSON-RPC result found in SSE")
        return {}, sid

    # Parse plain JSON
    try:
        data = r.json()
        # Check for non-standard error format
        if isinstance(data, dict) and "code" in data and "msg" in data:
            log(f"⚠ Non-standard error: code={data['code']} msg={data['msg']}")
        return data, sid
    except json.JSONDecodeError:
        log(f"ERROR: Not valid JSON: {body[:200]}")
        return {}, sid


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_glm_mcp.py <api_key> [query]")
        sys.exit(1)

    api_key = sys.argv[1]
    query = sys.argv[2] if len(sys.argv) > 2 else "OpenAI"

    print("=" * 60)
    print("Z.AI web_search_prime MCP Test")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Key: {api_key[:8]}...{api_key[-4:]}")
    print(f"Query: {query}")
    print("=" * 60)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_key}",
    }

    # ── Step 1: Initialize ────────────────────────────────────
    print("\n[1] Initialize")
    resp, sid = send(headers, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-test", "version": "1.0.0"},
    }, str(uuid.uuid4()))

    if "error" in resp:
        print(f"\n✗ Init failed: {resp['error']}")
        sys.exit(1)

    result = resp.get("result", {})
    server_info = result.get("serverInfo", {})
    protocol = result.get("protocolVersion", "?")
    print(f"\n✓ Server: {server_info.get('name')} v{server_info.get('version')}")
    print(f"  Protocol: {protocol}")
    print(f"  Capabilities: {list(result.get('capabilities', {}).keys())}")

    if sid:
        headers["Mcp-Session-Id"] = sid

    # ── Step 2: Initialized notification ──────────────────────
    print("\n[2] Send initialized notification")
    send(headers, "notifications/initialized")

    # ── Step 3: List tools ────────────────────────────────────
    print("\n[3] List tools")
    resp, _ = send(headers, "tools/list", None, str(uuid.uuid4()))
    tools = resp.get("result", {}).get("tools", [])
    for t in tools:
        print(f"\n  Tool: {t['name']}")
        print(f"  Description: {t.get('description', '?')[:100]}")
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for pname, pinfo in props.items():
            req = "REQUIRED" if pname in required else "optional"
            print(f"    {pname} ({req}): {pinfo.get('description', '?')[:80]}")

    # ── Step 4: Call tool with various parameter combos ───────
    print("\n[4] Search tests")

    test_cases = [
        # Basic
        {"search_query": query},
        # With location
        {"search_query": query, "location": "us"},
        {"search_query": query, "location": "cn"},
        # With content size
        {"search_query": query, "content_size": "high"},
        # With recency
        {"search_query": query, "search_recency_filter": "oneMonth"},
        # Chinese query
        {"search_query": "人工智能最新消息"},
        # Very simple single word
        {"search_query": "Google"},
        # URL-like
        {"search_query": "site:github.com OpenAI"},
    ]

    for i, args in enumerate(test_cases):
        print(f"\n  Test {i+1}: {json.dumps(args)[:100]}")
        resp, _ = send(headers, "tools/call", {
            "name": "web_search_prime",
            "arguments": args,
        }, str(uuid.uuid4()))

        if "error" in resp:
            print(f"  ✗ Error: {resp['error']}")
            continue

        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [])

        if is_error:
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            print(f"  ✗ Tool error: {' '.join(texts)[:200]}")
            continue

        for c in content:
            if c.get("type") == "text":
                text = c["text"]
                # Try to parse (might be double-encoded)
                parsed = text
                for _ in range(3):
                    if isinstance(parsed, (list, dict)):
                        break
                    try:
                        parsed = json.loads(parsed)
                    except (json.JSONDecodeError, TypeError):
                        break

                if isinstance(parsed, list):
                    print(f"  → {len(parsed)} results")
                    for r in parsed[:3]:
                        if isinstance(r, dict):
                            print(f"    • {r.get('title', '?')[:60]}")
                            print(f"      {r.get('link', r.get('url', '?'))[:60]}")
                elif isinstance(parsed, dict):
                    print(f"  → dict: {list(parsed.keys())[:5]}")
                else:
                    print(f"  → raw text: {str(parsed)[:150]}")

    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
