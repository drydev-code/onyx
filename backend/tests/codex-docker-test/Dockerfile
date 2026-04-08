FROM node:20-slim

# Install Codex CLI + D-Bus + gnome-keyring + Python for token refresh
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dbus \
        gnome-keyring \
        libsecret-1-0 \
        libsecret-tools \
        python3 \
        python3-pip \
        python3-gi \
        gir1.2-secret-1 \
        ca-certificates \
        curl && \
    npm install -g @openai/codex && \
    pip3 install --break-system-packages httpx secretstorage && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY test_codex_headless.sh /app/
COPY refresh_token.py /app/
COPY secret_service.py /app/
RUN chmod +x /app/test_codex_headless.sh

ENTRYPOINT ["/app/test_codex_headless.sh"]
