#!/usr/bin/env bash
# Print this project's Android applicationId (not hardcoded).
# Override: ANDROID_APP_ID or PIDCAT_PACKAGE
# Usage: android-app-id.sh [project-root]
set -eu

if [ -n "${ANDROID_APP_ID:-}" ]; then
  printf '%s\n' "$ANDROID_APP_ID"
  exit 0
fi
if [ -n "${PIDCAT_PACKAGE:-}" ]; then
  printf '%s\n' "$PIDCAT_PACKAGE"
  exit 0
fi

start="${1:-}"
if [ -z "$start" ]; then
  start="$(cd "$(dirname "$0")/.." && pwd)"
fi

root="$start"
found_root=0
while [ "$root" != "/" ]; do
  if [ -f "$root/settings.gradle.kts" ] || [ -f "$root/settings.gradle" ] || [ -x "$root/gradlew" ]; then
    found_root=1
    break
  fi
  root="$(dirname "$root")"
done
if [ "$found_root" -eq 0 ]; then
  root="$start"
fi

extract_id() {
  # first applicationId "…" / '…', else namespace
  local f="$1" id
  id="$(grep -E 'applicationId[[:space:]]*[=][[:space:]]*["'\''][^"'\'']+' "$f" 2>/dev/null \
    | head -1 \
    | sed -E 's/.*applicationId[[:space:]]*=[[:space:]]*["'\'']([^"'\'']+)["'\''].*/\1/')"
  if [ -n "$id" ]; then
    printf '%s\n' "$id"
    return 0
  fi
  id="$(grep -E 'namespace[[:space:]]*[=][[:space:]]*["'\''][^"'\'']+' "$f" 2>/dev/null \
    | head -1 \
    | sed -E 's/.*namespace[[:space:]]*=[[:space:]]*["'\'']([^"'\'']+)["'\''].*/\1/')"
  if [ -n "$id" ]; then
    printf '%s\n' "$id"
    return 0
  fi
  return 1
}

# Prefer typical Android app modules, then any Gradle file.
for cand in \
  "$root/app/build.gradle.kts" \
  "$root/app/build.gradle" \
  "$root/androidApp/build.gradle.kts" \
  "$root/androidApp/build.gradle" \
  "$root/composeApp/build.gradle.kts" \
  "$root/composeApp/build.gradle"
do
  [ -f "$cand" ] || continue
  extract_id "$cand" && exit 0
done

# Last resort: first applicationId in the tree (skip build dirs).
found="$(find "$root" \( -name build -o -name .gradle -o -name .git \) -prune -o \
  \( -name 'build.gradle.kts' -o -name 'build.gradle' \) -print 2>/dev/null | head -40)"
for cand in $found; do
  extract_id "$cand" && exit 0
done

echo "could not find applicationId under $root (set ANDROID_APP_ID)" >&2
exit 1
