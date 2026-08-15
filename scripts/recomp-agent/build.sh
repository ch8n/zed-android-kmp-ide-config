#!/usr/bin/env bash
# Rebuild scripts/recomp-agent.dex (sidecar — not part of the Android app).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
mkdir -p "$out/classes"
javac --release 11 -d "$out/classes" "$here/pixi/recomp/RecompAgent.java"
d8bin="$(command -v d8 || true)"
if [ -z "$d8bin" ]; then
  for c in \
    /opt/homebrew/share/android-commandlinetools/build-tools/*/d8 \
    "$ANDROID_HOME"/build-tools/*/d8 \
    "$HOME/Library/Android/sdk/build-tools/"*/d8
  do
    [ -x "$c" ] || continue
    d8bin="$c"
  done
fi
if [ -z "${d8bin:-}" ]; then
  echo "d8 not found (Android build-tools)" >&2
  exit 1
fi
"$d8bin" --output "$out" $(find "$out/classes" -name '*.class')
cp "$out/classes.dex" "$root/recomp-agent.dex"
echo "wrote $root/recomp-agent.dex"
