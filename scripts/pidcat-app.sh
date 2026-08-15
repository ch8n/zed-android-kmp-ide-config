#!/usr/bin/env bash
# Colored pidcat for the app package (see pidcat-app.py).
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  echo "Press Enter to close."
  read -r _
  exit 1
fi
exec python3 "$ROOT/pidcat-app.py" "$@"
