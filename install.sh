#!/usr/bin/env bash
# Install Zed Android/KMP config + pickers into a project.
# Usage:
#   ./install.sh [project-dir]
#   ./install.sh --force ~/code/my-app
#   curl -fsSL https://raw.githubusercontent.com/ch8n/zed-android-ide-config/main/install.sh | bash -s -- [project-dir]
#
# Does not install Xcode, Android SDK, or JDK. Optional: Homebrew pidcat.
set -euo pipefail

REPO_SLUG="ch8n/zed-android-ide-config"
REPO_URL="https://github.com/${REPO_SLUG}.git"
RAW_BASE="https://raw.githubusercontent.com/${REPO_SLUG}/main"
FORCE=0
TARGET=""

usage() {
  cat <<EOF
install.sh — copy Zed Android/KMP tasks, settings, and picker scripts

Usage:  install.sh [--force] [project-dir]

  project-dir   Android/KMP repo root (default: current directory)
  --force       overwrite without prompting (still writes .bak)

Does not install or update Xcode / Android SDK / JDK.
If Homebrew is present and pidcat is missing, installs pidcat.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -f|--force) FORCE=1; shift ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *) TARGET="$1"; shift ;;
  esac
done

if [ -z "$TARGET" ]; then
  TARGET="$PWD"
fi
TARGET="$(cd "$TARGET" && pwd)"

confirm() {
  [ "$FORCE" -eq 1 ] && return 0
  local ans
  if [ -r /dev/tty ]; then
    printf '%s [y/N] ' "$1" > /dev/tty
    read -r ans < /dev/tty || true
    case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
  fi
  echo "non-interactive: pass --force to overwrite / auto-yes" >&2
  return 1
}

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# Resolve source tree: this clone, or fetch into a temp dir.
SRC=""
CLEANUP_SRC=""
resolve_src() {
  local here
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$here/.zed/tasks.json" ] && [ -f "$here/scripts/android-device-picker.sh" ]; then
      SRC="$here"
      return 0
    fi
  fi
  if need_cmd git; then
    CLEANUP_SRC="$(mktemp -d "${TMPDIR:-/tmp}/zed-android-ide-config.XXXXXX")"
    echo "cloning ${REPO_URL} …"
    git clone --depth 1 "$REPO_URL" "$CLEANUP_SRC"
    SRC="$CLEANUP_SRC"
    return 0
  fi
  echo "need git to fetch ${REPO_SLUG}" >&2
  exit 1
}

backup() {
  local f="$1"
  [ -e "$f" ] || return 0
  cp -R "$f" "${f}.bak"
  echo "  backup  ${f} -> ${f}.bak"
}

install_files() {
  mkdir -p "$TARGET/.zed" "$TARGET/scripts"

  if [ -e "$TARGET/.zed/tasks.json" ] || [ -e "$TARGET/.zed/settings.json" ]; then
    if ! confirm "overwrite $TARGET/.zed/{tasks,settings}.json ?"; then
      echo "skip .zed (kept existing)"
    else
      backup "$TARGET/.zed/tasks.json"
      backup "$TARGET/.zed/settings.json"
      cp "$SRC/.zed/tasks.json" "$TARGET/.zed/tasks.json"
      cp "$SRC/.zed/settings.json" "$TARGET/.zed/settings.json"
      echo "  wrote   $TARGET/.zed/tasks.json"
      echo "  wrote   $TARGET/.zed/settings.json"
    fi
  else
    cp "$SRC/.zed/tasks.json" "$TARGET/.zed/tasks.json"
    cp "$SRC/.zed/settings.json" "$TARGET/.zed/settings.json"
    echo "  wrote   $TARGET/.zed/tasks.json"
    echo "  wrote   $TARGET/.zed/settings.json"
  fi

  local s
  for s in android-device-picker.sh gradle-task-picker.sh ios-simulator-picker.sh; do
    if [ -e "$TARGET/scripts/$s" ]; then
      if confirm "overwrite $TARGET/scripts/$s ?"; then
        backup "$TARGET/scripts/$s"
        cp "$SRC/scripts/$s" "$TARGET/scripts/$s"
        echo "  wrote   $TARGET/scripts/$s"
      else
        echo "  skip    $TARGET/scripts/$s"
      fi
    else
      cp "$SRC/scripts/$s" "$TARGET/scripts/$s"
      echo "  wrote   $TARGET/scripts/$s"
    fi
  done
  chmod +x "$TARGET/scripts/"*.sh
}

maybe_pidcat() {
  if need_cmd pidcat; then
    echo "pidcat    ok ($(command -v pidcat))"
    return 0
  fi
  if ! need_cmd brew; then
    echo "pidcat    missing (install: https://github.com/JakeWharton/pidcat)"
    return 0
  fi
  if confirm "pidcat not found. brew install pidcat ?"; then
    brew install pidcat
    echo "pidcat    installed"
  else
    echo "pidcat    skipped"
  fi
}

check_env() {
  echo
  echo "checks (informational — nothing is installed here)"
  if [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/java" ]; then
    echo "JAVA_HOME ok  $JAVA_HOME"
  elif [ -x /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin/java ]; then
    echo "JAVA_HOME default Homebrew openjdk@17 is present"
  else
    echo "JAVA_HOME not found — edit .zed/settings.json to match your JDK"
  fi

  local sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/homebrew/share/android-commandlinetools}}"
  if [ -x "$sdk/platform-tools/adb" ] || need_cmd adb; then
    echo "adb       ok"
  else
    echo "adb       missing — set ANDROID_HOME (SDK is not auto-installed)"
  fi
  if [ -x "$sdk/emulator/emulator" ] || need_cmd emulator; then
    echo "emulator  ok"
  else
    echo "emulator  missing — SDK emulator package is not auto-installed"
  fi
  if need_cmd xcrun && xcrun simctl help >/dev/null 2>&1; then
    echo "simctl    ok"
  else
    echo "simctl    unavailable (iOS picker will show an error; Xcode is not installed)"
  fi
}

main() {
  echo "target    $TARGET"
  resolve_src
  echo "source    $SRC"
  install_files
  maybe_pidcat
  check_env
  if [ -n "$CLEANUP_SRC" ]; then
    rm -rf "$CLEANUP_SRC"
  fi
  echo
  echo "done. In Zed: Cmd+Shift+R → Gradle: Tasks / Android: Devices & emulators"
  echo "edit .zed/settings.json if JAVA_HOME / ANDROID_HOME differ on this machine"
  echo "edit package id in .zed/tasks.json (default com.example.piximons)"
}

main
