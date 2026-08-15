#!/usr/bin/env bash
# Opens layout inspector + live recomposition counts.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$root/scripts/interactive_inspector_recomp.py" "$@"
