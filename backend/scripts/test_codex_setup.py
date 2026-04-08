"""Refresh Codex OAuth token and write auth.json + token file.

Reads PGPASSWORD (and other psql env vars) from the environment. See
backend/.env.example for the full list.
"""
import json
import os
import subprocess
import sys

if not os.environ.get("PGPASSWORD"):
    print(
        "ERROR: PGPASSWORD not set. Source backend/.env (see .env.example).",
        file=sys.stderr,
    )
    sys.exit(1)

sys.path.insert(0, "/app")
from onyx.server.manage.llm.codex_oauth import refresh_access_token  # noqa: E402

# Get refresh token from DB
r = subprocess.run(
    [
        "psql", "-U", "postgres", "-h", "relational_db",
        "-d", "postgres", "-t", "-A", "-c",
        "SELECT custom_config FROM llm_provider WHERE provider='openai_codex'",
    ],
    capture_output=True, text=True,
)

if not r.stdout.strip():
    # Fallback to previously copied file
    with open("/tmp/codex_cfg.json") as f:
        cfg = json.loads(f.read().strip())
else:
    cfg = json.loads(r.stdout.strip())

refresh_token = cfg.get("codex_refresh_token", "")
if not refresh_token:
    print("ERROR: No refresh token found in DB")
    sys.exit(1)

print("Refreshing token...")
new = refresh_access_token(refresh_token)
print(f"Got new token: {len(new.access_token)} chars, expires_in={new.expires_in}")

# Write auth.json
codex_home = os.path.expanduser("~/.codex")
os.makedirs(codex_home, exist_ok=True)
auth = {
    "auth_mode": "chatgpt",
    "tokens": {
        "access_token": new.access_token,
        "refresh_token": new.refresh_token or refresh_token,
        "id_token": new.access_token,
    },
}
with open(os.path.join(codex_home, "auth.json"), "w") as f:
    json.dump(auth, f)
print("auth.json written")

# Write token to temp file for keyring storage
with open("/tmp/codex_token.txt", "w") as f:
    f.write(new.access_token)
print("Token file written")
