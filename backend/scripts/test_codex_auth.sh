#!/bin/bash
# Test script for Codex CLI OAuth auth in Docker container
set -e

echo "=== Step 1: Refresh token and write auth.json ==="
python3 /app/scripts/test_codex_setup.py

echo "=== Step 2: Start D-Bus session ==="
export DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --print-address --fork 2>/dev/null)
echo "DBUS: $DBUS_SESSION_BUS_ADDRESS"

echo "=== Step 3: Start gnome-keyring with Secret Service ==="
# Kill any existing keyring daemons
pkill gnome-keyring-daemon 2>/dev/null || true
sleep 0.5

# Start with --replace and --daemonize, providing empty password on stdin
eval $(echo "" | gnome-keyring-daemon --replace --daemonize --components=secrets,pkcs11 2>/dev/null)
echo "GNOME_KEYRING_CONTROL=$GNOME_KEYRING_CONTROL"

# Check if Secret Service is registered on D-Bus
dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>&1 | grep -o "org.freedesktop.secrets" || echo "WARNING: Secret Service not on D-Bus"
dbus-send --session --print-reply --dest=org.gnome.keyring /org/freedesktop/secrets org.freedesktop.DBus.Introspectable.Introspect 2>&1 | head -5

echo "=== Step 4: Store token via Python secretstorage ==="
python3 << 'PYEOF'
import secretstorage, os

connection = secretstorage.dbus_init()

# List all collections
bus = connection
collections = list(secretstorage.get_all_collections(connection))
print(f"Collections: {[c.get_label() for c in collections]}")

# Try to get or create default
try:
    collection = secretstorage.get_default_collection(connection)
    print(f"Default collection: {collection.get_label()}")
except Exception as e:
    print(f"No default collection: {e}")
    # Try creating via D-Bus directly
    try:
        collection = secretstorage.create_collection(connection, 'login', alias='default')
        print("Created login collection")
    except Exception as e2:
        print(f"Create failed: {e2}")
        # Last resort: try with the first available collection
        if collections:
            collection = collections[0]
            print(f"Using first collection: {collection.get_label()}")
        else:
            print("FATAL: No collections available")
            exit(1)

if collection.is_locked():
    collection.unlock()

with open('/tmp/codex_token.txt') as f:
    token = f.read().strip()

collection.create_item(
    'Codex Auth Token',
    {'service': 'Codex MCP Credentials', 'username': 'codex-auth',
     'application': 'rust-keyring', 'target': 'default'},
    token.encode(),
    replace=True,
)
print(f"Token stored ({len(token)} chars)")
items = list(collection.search_items({'service': 'Codex MCP Credentials'}))
print(f"Verified: {len(items)} items")
PYEOF
echo "Keyring setup exit: $?"

echo "=== Step 5: Test Codex CLI ==="
echo "ENV: DBUS=$DBUS_SESSION_BUS_ADDRESS KEYRING=$GNOME_KEYRING_CONTROL"
RUST_LOG=debug timeout 90 codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --skip-git-repo-check \
    --ephemeral \
    -o /tmp/codex-final.txt \
    -m gpt-5.4 \
    "What is 2+2? Reply with just the number." \
    2>&1 | grep -iE "keyring|secret|dbus|token data|auth_mode|bearer|401|500|websocket_connect" | head -20
EXIT=${PIPESTATUS[0]}
echo "Exit: $EXIT"
echo "--- output ---"
cat /tmp/codex-final.txt 2>/dev/null || echo "NO OUTPUT FILE"
