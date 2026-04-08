# Onyx Server Deploy Guide

Quick reference for building and deploying to the onyx server.

## Prerequisites

- Docker Desktop running locally
- SSH key at `~/.ssh/id_ed25519` with access to `root@onyx`
- Git repo at `C:\Repositories\Github\onyx`

## Quick Deploy Commands

### Backend only (fast, ~30s after first build)

```bash
cd backend
docker build -t onyxdotapp/onyx-backend:craft-latest \
  --build-arg BASE_IMAGE=onyxdotapp/onyx-backend:craft-latest \
  -f Dockerfile.dev .
```

```bash
SSH_KEY="$HOME/.ssh/id_ed25519"
SSH="ssh -i $SSH_KEY root@onyx"
docker save onyxdotapp/onyx-backend:craft-latest | $SSH "docker load"
$SSH "cd /var/onyx/onyx_data/deployment && docker compose up -d --force-recreate api_server background && docker compose restart nginx"
```

### Web only (~4min build)

```bash
cd web
docker build -t onyxdotapp/onyx-web-server:craft-latest -f Dockerfile.dev .
```

```bash
SSH_KEY="$HOME/.ssh/id_ed25519"
SSH="ssh -i $SSH_KEY root@onyx"
docker save onyxdotapp/onyx-web-server:craft-latest | $SSH "docker load"
$SSH "cd /var/onyx/onyx_data/deployment && docker compose up -d --force-recreate web_server && docker compose restart nginx"
```

### Both (use deploy-dev.sh)

```bash
./deploy-dev.sh           # Build and deploy both
./deploy-dev.sh backend   # Backend only
./deploy-dev.sh web       # Web only
```

### Full backend rebuild (when Dockerfile.dev layers exceed max depth)

```bash
cd backend
docker build -t onyxdotapp/onyx-backend:craft-latest \
  --build-arg ENABLE_CRAFT=true \
  --build-arg ENABLE_CLI_PROVIDERS=true \
  -f Dockerfile .
```

This resets layers. Use the same push commands as above.

## Build Args

| Arg | Default | Description |
|-----|---------|-------------|
| `ENABLE_CRAFT` | `false` | Include Node.js + opencode CLI for Craft |
| `ENABLE_CLI_PROVIDERS` | `false` | Include Claude Code CLI + Codex CLI |

## After Deploy: Re-setup Codex Auth

Container restarts lose the Codex auth.json. Re-setup:

```bash
SSH="ssh -i ~/.ssh/id_ed25519 root@onyx"

# Copy tokens from DB and run setup script
$SSH 'docker exec onyx-relational_db-1 psql -U postgres -d postgres -t -A \
  -c "SELECT custom_config FROM llm_provider WHERE provider='\''openai_codex'\''" \
  > /tmp/cc.json && \
  docker cp /tmp/cc.json onyx-api_server-1:/tmp/cc.json && \
  docker cp /tmp/setup_codex_auth.py onyx-api_server-1:/tmp/setup_codex_auth.py && \
  docker exec onyx-api_server-1 python3 /tmp/setup_codex_auth.py'
```

If tokens are expired, do a fresh device auth:

```bash
$SSH 'docker exec -d onyx-api_server-1 \
  bash -c "mkdir -p /root/.codex && \
  echo cli_auth_credentials_store = \\\"file\\\" > /root/.codex/config.toml && \
  timeout 180 codex login --device-auth > /tmp/codex-login.log 2>&1"'
sleep 5
$SSH 'docker exec onyx-api_server-1 cat /tmp/codex-login.log'
# Enter the code at https://auth.openai.com/codex/device
```

## Troubleshooting

### "max depth exceeded" on docker build

Too many Dockerfile.dev overlay layers. Do a full rebuild:

```bash
docker build -t onyxdotapp/onyx-backend:craft-latest \
  --build-arg ENABLE_CRAFT=true --build-arg ENABLE_CLI_PROVIDERS=true \
  -f Dockerfile .
```

### Check server logs

```bash
SSH="ssh -i ~/.ssh/id_ed25519 root@onyx"
$SSH "docker logs onyx-api_server-1 --tail 50"
$SSH "docker logs onyx-web_server-1 --tail 50"
$SSH "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

### DB queries

```bash
SSH="ssh -i ~/.ssh/id_ed25519 root@onyx"
$SSH "docker exec onyx-relational_db-1 psql -U postgres -d postgres -c 'SELECT id, provider, name FROM llm_provider'"
```
