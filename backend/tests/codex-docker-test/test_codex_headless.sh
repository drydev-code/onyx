#!/bin/bash
# Isolated test: Codex CLI with ChatGPT OAuth in headless Docker
# Key insight: cli_auth_credentials_store = "file" bypasses system keyring
set -uo pipefail

echo "=========================================="
echo " Codex CLI Headless OAuth Test"
echo " $(codex --version 2>&1)"
echo "=========================================="

# ── 1: Get token ─────────────────────────────────────────────
ACCESS_TOKEN="${CODEX_ACCESS_TOKEN:-}"
REFRESH_TOKEN="${CODEX_REFRESH_TOKEN:-}"
if [ -z "$ACCESS_TOKEN" ] && [ -n "$REFRESH_TOKEN" ]; then
    TOKEN_JSON=$(python3 /app/refresh_token.py)
    ACCESS_TOKEN=$(echo "$TOKEN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    REFRESH_TOKEN=$(echo "$TOKEN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")
fi
[ -z "$ACCESS_TOKEN" ] && echo "ERROR: Set CODEX_ACCESS_TOKEN or CODEX_REFRESH_TOKEN" && exit 1
echo "[1] Token: ${#ACCESS_TOKEN} chars"

# ── 2: Write config.toml + auth.json ─────────────────────────
mkdir -p ~/.codex
cat > ~/.codex/config.toml << 'TOML'
cli_auth_credentials_store = "file"
TOML
echo "[2] config.toml: cli_auth_credentials_store = file"

python3 -c "
import json, os
t = os.environ['CODEX_ACCESS_TOKEN']
r = os.environ.get('CODEX_REFRESH_TOKEN', '')
auth = {'auth_mode':'chatgpt','tokens':{'access_token':t,'refresh_token':r,'id_token':t}}
with open(os.path.expanduser('~/.codex/auth.json'),'w') as f:
    json.dump(auth, f)
print('    auth.json written:', len(t), 'char token')
" || exit 1
codex login status 2>&1 | head -1

# ── 3: Run Codex CLI ─────────────────────────────────────────
echo ""
echo "[3] Running Codex CLI..."
timeout 90 codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --skip-git-repo-check \
    --ephemeral \
    -o /tmp/codex-out.txt \
    -m gpt-5.4 \
    "What is 2+2? Reply with just the number." \
    2>/tmp/codex.err
EXIT=$?
echo "Exit: $EXIT"
echo "Output: $(cat /tmp/codex-out.txt 2>/dev/null || echo 'NONE')"
if [ $EXIT -ne 0 ]; then
    echo "Errors:"
    tail -5 /tmp/codex.err
fi
echo "=========================================="
