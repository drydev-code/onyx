"""Setup Codex CLI auth from DB tokens."""
import json
import os
import sys

sys.path.insert(0, "/app")

with open("/tmp/cc.json") as f:
    cfg = json.loads(f.read().strip())

from onyx.llm.codex_cli import CodexCLI

cli = CodexCLI(model_name="gpt-5.4", custom_config=cfg)
cli._setup_auth()

print("config.toml:", open(os.path.expanduser("~/.codex/config.toml")).read().strip())
auth = json.load(open(os.path.expanduser("~/.codex/auth.json")))
print("id_token:", len(auth["tokens"].get("id_token", "")))
print("access_token:", len(auth["tokens"].get("access_token", "")))
print("account_id:", auth["tokens"].get("account_id", "")[:10])
