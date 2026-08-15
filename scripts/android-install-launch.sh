#!/usr/bin/env bash
# Install the debug APK and launch the launcher activity.
# Root project has :app:installDebug, not installDebug.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PKG="${ANDROID_APP_ID:-com.example.piximons}"
ACTIVITY="${ANDROID_LAUNCH_ACTIVITY:-com.example.piximons.MainActivity}"

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

echo "Launching $PKG/$ACTIVITY ..."
# am start returns 0 even on "Error type 3" — inspect stdout.
out="$(adb shell am start -n "$PKG/$ACTIVITY" 2>&1 || true)"
printf '%s\n' "$out"
if printf '%s\n' "$out" | grep -Eiq 'Error|does not exist|Exception|Unable to resolve'; then
  echo "Launch failed." >&2
  exit 1
fi

echo "OK: $PKG is installed and launched."
