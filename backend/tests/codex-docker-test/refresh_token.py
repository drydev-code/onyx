"""Refresh Codex OAuth token and output fresh access token."""
import json
import os
import sys

import httpx

_AUTH_BASE = "https://auth.openai.com"
_OAUTH_TOKEN_URL = f"{_AUTH_BASE}/oauth/token"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


def refresh(refresh_token: str) -> dict:
    response = httpx.post(
        _OAUTH_TOKEN_URL,
        data={
            "client_id": _CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    rt = os.environ.get("CODEX_REFRESH_TOKEN", "")
    if not rt:
        print("ERROR: Set CODEX_REFRESH_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    data = refresh(rt)
    # Output as JSON for the shell script to parse
    print(json.dumps({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", rt),
        "id_token": data.get("id_token", data["access_token"]),
        "expires_in": data.get("expires_in", 3600),
    }))
