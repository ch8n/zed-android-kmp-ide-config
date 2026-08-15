#!/usr/bin/env bash
# Generate Compose compiler stability reports and open an interactive TUI.
# Project-agnostic: no app source / build.gradle edits (uses an init script).
set -u

JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export JAVA_HOME
export PATH="$JAVA_HOME/bin:/opt/homebrew/bin:$PATH"

HERE="$(cd "$(dirname "$0")" && pwd)"

die() {
  printf '\nERROR\n%s\n\nPress Enter to close.\n' "$*"
  read -r _ < /dev/tty || true
  exit 1
}

find_root() {
  local d="${1:-$PWD}"
  while [ "$d" != "/" ]; do
    [ -x "$d/gradlew" ] && { printf '%s' "$d"; return 0; }
    d="$(dirname "$d")"
  done
  return 1
}

ROOT="$(find_root "${1:-$PWD}")" || die "no gradlew in this project (or parents)"
INIT="$HERE/compose-reports.init.gradle"
[ -f "$INIT" ] || die "missing $INIT"

# Resolve compile tasks that exist (Android app vs KMP). Gradle 9 fails
# the whole run if you name a task that is not in the project.
list_compile_tasks() {
  (
    cd "$ROOT" || exit 1
    ./gradlew tasks --all
  ) 2>/dev/null | awk '
    /^[A-Za-z0-9:_-]*compile[A-Za-z0-9]*Kotlin[A-Za-z0-9]*($| )/ {
      t = $1
      if (t ~ /Test/) next
      if (t ~ /Release/) next
      if (t ~ /compileDebugKotlin$/ || t ~ /compileDebugKotlinAndroid$/) print t
    }
  ' | sort -u
}

if [ "${COMPOSE_STABILITY_SKIP_BUILD:-}" != "1" ]; then
  echo "Resolving Kotlin compile tasks…"
  echo "  $ROOT"
  tasks="$(list_compile_tasks || true)"
  if [ -z "$tasks" ]; then
    die "no compileDebugKotlin / compileDebugKotlinAndroid task in this project"
  fi
  echo "Generating Compose compiler reports:"
  echo "$tasks" | sed 's/^/  /'
  echo "(rerunning compile so the Compose compiler actually writes reports)"
  set +e
  # shellcheck disable=SC2086
  (
    cd "$ROOT" || exit 1
    # Config cache + UP-TO-DATE skips the compiler, so no *-composables.txt.
    ./gradlew --init-script "$INIT" \
      --no-configuration-cache \
      --rerun-tasks \
      $tasks
  )
  code=$?
  set -e
  if [ "$code" -ne 0 ]; then
    echo "Gradle exited $code — looking for any reports already written…"
  fi
fi

python3 "$HERE/compose-stability-report.py" "$ROOT" || die "stability report TUI failed"
