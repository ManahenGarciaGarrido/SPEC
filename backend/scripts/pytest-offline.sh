#!/usr/bin/env bash
# Run the whole test suite inside a Linux network namespace that only has
# loopback: the OS-level proof of "no network" (it also covers native code
# that bypasses Python's sockets). Requires unprivileged user namespaces.
# Usage: scripts/pytest-offline.sh [pytest args...]   (after `uv sync`)
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
exec unshare --user --map-root-user --net -- \
  sh -c '"$0" scripts/netns_check.py && exec "$0" -m pytest "$@"' "$PYTHON" "$@"
