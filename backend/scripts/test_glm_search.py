"""Test GLM web search via chat completions API.

Set GLM_API_KEY in backend/.env before running (see backend/.env.example).
"""
import json
import os
import sys

import requests

KEY = os.environ.get("GLM_API_KEY", "")
if not KEY:
    print("ERROR: set GLM_API_KEY (see backend/.env.example)", file=sys.stderr)
    sys.exit(1)

BASE = "https://api.z.ai/api/coding/paas/v4/chat/completions"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

for model in ["glm-4-flash", "glm-5.1", "glm-5"]:
    try:
        r = requests.post(BASE, headers=HEADERS, json={
            "model": model,
            "messages": [{"role": "user", "content": "Search web for: OpenAI latest news 2026. Return a JSON array of results with title, link, snippet."}],
            "tools": [{"type": "web_search", "web_search": {"enable": True}}],
            "max_tokens": 2000,
        }, timeout=60)
        data = r.json()
        if "error" in data:
            print(f"{model}: ERROR {data['error']['message'][:80]}")
            continue
        msg = data["choices"][0]["message"]
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        print(f"{model}: content={content[:200]}")
        if reasoning:
            print(f"  reasoning={reasoning[:150]}")
        # Check for web_search refs
        raw = json.dumps(data)
        if "web_search" in raw:
            print(f"  web_search references found in response")
        break
    except Exception as e:
        print(f"{model}: {e}")
