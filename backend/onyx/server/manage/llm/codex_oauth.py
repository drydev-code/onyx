"""OpenAI Codex OAuth device code flow implementation.

Implements OpenAI's custom device authorization flow for Codex,
which uses ChatGPT accounts for authentication.

Flow:
1. POST /api/accounts/deviceauth/usercode → {device_auth_id, user_code, interval}
2. User visits https://auth.openai.com/codex/device and enters user_code
3. Poll /api/accounts/deviceauth/token → {authorization_code, code_verifier, code_challenge}
4. Exchange authorization_code for tokens via /oauth/token
"""

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()

# OpenAI auth endpoints (from Codex CLI source)
_AUTH_BASE = "https://auth.openai.com"
_DEVICE_USERCODE_URL = f"{_AUTH_BASE}/api/accounts/deviceauth/usercode"
_DEVICE_TOKEN_URL = f"{_AUTH_BASE}/api/accounts/deviceauth/token"
_OAUTH_TOKEN_URL = f"{_AUTH_BASE}/oauth/token"
_DEVICE_CALLBACK_URL = f"{_AUTH_BASE}/deviceauth/callback"
_VERIFICATION_URL = f"{_AUTH_BASE}/codex/device"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


class DeviceAuthResponse:
    """Response from the device authorization request."""

    def __init__(
        self,
        device_auth_id: str,
        user_code: str,
        verification_uri: str,
        interval: int,
    ):
        self.device_auth_id = device_auth_id
        self.user_code = user_code
        self.verification_uri = verification_uri
        self.interval = interval


class TokenResponse:
    """Response from the token exchange."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None,
        id_token: str | None,
        expires_in: int,
        token_type: str = "Bearer",
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.id_token = id_token
        self.expires_in = expires_in
        self.token_type = token_type


def initiate_device_auth() -> DeviceAuthResponse:
    """Start the device authorization flow.

    Returns a DeviceAuthResponse with user_code and verification_uri
    that the user needs to visit to authorize.
    """
    response = httpx.post(
        _DEVICE_USERCODE_URL,
        json={"client_id": _CLIENT_ID},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    data = response.json()

    return DeviceAuthResponse(
        device_auth_id=data["device_auth_id"],
        user_code=data.get("user_code") or data.get("usercode", ""),
        verification_uri=_VERIFICATION_URL,
        interval=int(data.get("interval", "5")),
    )


def poll_for_token(device_auth_id: str, user_code: str) -> TokenResponse | None:
    """Poll for authorization after user enters the code.

    Returns TokenResponse if authorized, None if still pending.
    Raises on error or expiration.
    """
    # Step 1: Poll for the authorization code
    response = httpx.post(
        _DEVICE_TOKEN_URL,
        json={
            "device_auth_id": device_auth_id,
            "user_code": user_code,
        },
        headers={"Content-Type": "application/json"},
    )

    if response.status_code in (403, 404):
        # Still pending
        return None

    if not response.is_success:
        raise ValueError(
            f"Device auth failed with status {response.status_code}: {response.text}"
        )

    data = response.json()
    authorization_code = data.get("authorization_code")
    code_verifier = data.get("code_verifier")

    if not authorization_code:
        return None

    # Step 2: Exchange authorization code for tokens
    token_response = httpx.post(
        _OAUTH_TOKEN_URL,
        data={
            "client_id": _CLIENT_ID,
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": _DEVICE_CALLBACK_URL,
            "code_verifier": code_verifier or "",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token_response.raise_for_status()
    token_data = token_response.json()

    return TokenResponse(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        id_token=token_data.get("id_token"),
        expires_in=token_data.get("expires_in", 3600),
        token_type=token_data.get("token_type", "Bearer"),
    )


def refresh_access_token(refresh_token: str) -> TokenResponse:
    """Refresh an expired access token using the refresh token."""
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
    data = response.json()

    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token),
        id_token=data.get("id_token"),
        expires_in=data.get("expires_in", 3600),
        token_type=data.get("token_type", "Bearer"),
    )
