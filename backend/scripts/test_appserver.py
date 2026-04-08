"""Test Codex app-server stdio for streaming deltas."""
import json
import subprocess
import sys
import time

proc = subprocess.Popen(
    ["codex", "app-server", "--listen", "stdio://"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)


def send(msg):
    """Send as newline-delimited JSON (JSONL)."""
    data = json.dumps(msg) + "\n"
    proc.stdin.write(data.encode())
    proc.stdin.flush()


import select

def read_msg(timeout_sec=30):
    """Read one JSON line from stdout."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)
        if not ready:
            continue
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            print("bad json:", line[:100], flush=True)
            continue
    print("read_msg: timeout", flush=True)
    return None


import threading

stderr_lines = []
def drain_stderr():
    for line in iter(proc.stderr.readline, b""):
        stderr_lines.append(line.decode("utf-8", errors="replace").strip())

t = threading.Thread(target=drain_stderr, daemon=True)
t.start()

try:
    # Initialize
    send({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "clientInfo": {"name": "onyx-test", "version": "1.0"},
            "apiVersion": "v2",
        },
    })
    resp = read_msg()
    print("init:", json.dumps(resp)[:200], flush=True)

    send({"jsonrpc": "2.0", "method": "initialized"})

    # Start thread
    send({
        "jsonrpc": "2.0", "id": 1, "method": "thread/start",
        "params": {"instructions": "Answer briefly.", "model": "gpt-5.4"},
    })

    # Read until we get the thread/start response or thread/started notification
    tid = None
    for _ in range(15):
        msg = read_msg()
        if not msg:
            break
        method = msg.get("method", "")
        # Response to thread/start (id=1)
        if msg.get("id") == 1 and "result" in msg:
            result = msg["result"]
            thread_obj = result.get("thread", result)
            tid = thread_obj.get("id", result.get("threadId", ""))
            print("thread response:", tid[:40] if tid else json.dumps(result)[:200], flush=True)
        # Notification: thread/started has threadId in params
        elif method == "thread/started":
            tid = msg.get("params", {}).get("threadId", tid)
            print("thread/started:", tid[:30] if tid else "?", flush=True)
        else:
            print("pre:", str(method or msg.get("id", "?"))[:60], flush=True)
        if tid:
            break

    if not tid:
        print("ERROR: no thread ID", flush=True)
        sys.exit(1)

    # Send user input
    send({
        "jsonrpc": "2.0", "id": 2, "method": "thread/userInput",
        "params": {
            "threadId": tid,
            "content": [{"type": "input_text", "text": "What is 2+2? Just the number."}],
        },
    })

    # Drain remaining pre-events (mcp, etc) before reading deltas
    for _ in range(5):
        msg = read_msg(timeout_sec=3)
        if not msg:
            break
        print("drain:", str(msg.get("method", ""))[:60], flush=True)

    # Read streaming events
    deadline = time.time() + 45
    count = 0
    while time.time() < deadline and count < 100:
        msg = read_msg()
        if not msg:
            break
        method = msg.get("method", "")
        params = msg.get("params", {})

        if "delta" in method.lower():
            delta = params.get("delta", "")
            print("DELTA:", method, repr(delta)[:80], flush=True)
        elif "completed" in method.lower():
            print("DONE:", method, flush=True)
            if "turn" in method:
                break
        elif "started" in method.lower():
            print("START:", method, flush=True)
        elif "result" in msg:
            print("RESP:", msg.get("id"), flush=True)
        else:
            print("evt:", method[:60], flush=True)
        count += 1

except Exception as e:
    print("ERROR:", e, flush=True)
    import traceback
    traceback.print_exc()
finally:
    proc.terminate()
    proc.wait()
    if stderr_lines:
        print("STDERR:", flush=True)
        for l in stderr_lines[-10:]:
            print(" ", l, flush=True)
