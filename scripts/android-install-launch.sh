#!/usr/bin/env bash
# Install the debug APK and launch the launcher activity.
# Root project has :app:installDebug, not installDebug.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HERE="$(cd "$(dirname "$0")" && pwd)"
PKG="${ANDROID_APP_ID:-}"
if [ -z "$PKG" ]; then
  PKG="$("$HERE/android-app-id.sh" "$ROOT")"
fi

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not on PATH" >&2
  exit 1
fi

echo "Waiting for a device..."
adb wait-for-device
boot="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
if [ "$boot" != "1" ]; then
  echo "Device attached but not booted yet (sys.boot_completed=$boot)." >&2
  echo "Wait for the emulator home screen, then run again." >&2
  exit 1
fi

echo "Installing :app:installDebug ..."
./gradlew :app:installDebug --console=plain

echo "Launching launcher for $PKG ..."
if [ -n "${ANDROID_LAUNCH_ACTIVITY:-}" ]; then
  out="$(adb shell am start -n "$PKG/${ANDROID_LAUNCH_ACTIVITY}" 2>&1 || true)"
else
  out="$(adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 2>&1 || true)"
fi
printf '%s\n' "$out"
if printf '%s\n' "$out" | grep -Eiq 'Error type|does not exist|Exception|Unable to resolve|No activities found|monkey aborted'; then
  echo "Launch failed." >&2
  exit 1
fi

echo "OK: $PKG is installed and launched."
