"""Patch docker-compose.yml to wire Traefik HTTPS routing for the Onyx service.

Reads the public hostname from the ONYX_PUBLIC_HOST env var so this script
stays portable across deployments. Example:

    ONYX_PUBLIC_HOST=onyx.example.com python fix_labels.py
"""
import os
import sys

COMPOSE_PATH = os.environ.get(
    "ONYX_COMPOSE_PATH", "/var/onyx/onyx_data/deployment/docker-compose.yml"
)
PUBLIC_HOST = os.environ.get("ONYX_PUBLIC_HOST", "")
if not PUBLIC_HOST:
    print("ERROR: set ONYX_PUBLIC_HOST (see backend/.env.example)", file=sys.stderr)
    sys.exit(1)

with open(COMPOSE_PATH, "r") as f:
    c = f.read()

old = '      - "traefik.http.services.onyx.loadbalancer.server.port=80"'
new = (
    '      - "traefik.http.services.onyx.loadbalancer.server.port=80"\n'
    f'      - "traefik.http.routers.onyx-http.rule=Host(`{PUBLIC_HOST}`)"\n'
    '      - "traefik.http.routers.onyx-http.entrypoints=web"\n'
    '      - "traefik.http.routers.onyx-http.middlewares=onyx-redirect"\n'
    '      - "traefik.http.middlewares.onyx-redirect.redirectscheme.scheme=https"\n'
    '      - "traefik.http.middlewares.onyx-redirect.redirectscheme.permanent=true"'
)

c = c.replace(old, new, 1)
with open(COMPOSE_PATH, "w") as f:
    f.write(c)
print("done")
