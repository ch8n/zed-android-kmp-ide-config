# zed-android-ide-config

Zed workspace config for Android / Kotlin / KMP: tasks, JDK/SDK env, and interactive TUI pickers (devices, Gradle tasks, iOS sims).

Designed so **Zed + CLI + Gradle share one JDK** (no extra daemons). Interactive pickers open as **center editor tabs**. Failures stay visible (`hide: on_success` + Enter to close).

## Install

From a clone:

```bash
./install.sh /path/to/your-android-or-kmp-project
# or, inside the project:
./install.sh --force .
```

One-liner (clones this repo to a temp dir, then copies files):

```bash
curl -fsSL https://raw.githubusercontent.com/ch8n/zed-android-ide-config/main/install.sh | bash -s -- --force /path/to/your-project
```

`--force` overwrites existing `.zed` / picker scripts (writes `.bak` first).  
Does **not** install Xcode, Android SDK, or a JDK. If Homebrew is present, it can install **pidcat**.

Reload Zed tasks (`task: spawn` / Cmd+Shift+R).

## What’s included

| Path | Role |
|---|---|
| `.zed/settings.json` | `JAVA_HOME` / `ANDROID_HOME` for terminal + kotlin-lsp |
| `.zed/tasks.json` | Assemble, install, pidcat, pickers, tests, clean |
| `scripts/android-device-picker.sh` | ↑↓ AVD/USB: start/stop, logcat, new/delete AVD |
| `scripts/gradle-task-picker.sh` | Type-to-filter all Gradle tasks, Enter to run |
| `scripts/ios-simulator-picker.sh` | ↑↓ existing sims only — **never** installs Xcode |

## Tasks

- **Android: Devices & emulators** — center tab
- **Gradle: Tasks (filter & run)** — center tab
- **iOS: Simulators** — center tab (no-op install)
- **Emulator: Start small_phone (lite)** — center tab
- pidcat variants stay in the terminal dock
- assemble / install / tests / clean reuse the existing terminal

## Env you should edit

Defaults match a Homebrew layout on Apple Silicon:

- `JAVA_HOME` → `/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` → `/opt/homebrew/share/android-commandlinetools`

Change those in `.zed/settings.json` (and optionally `~/.config/zed/settings.json`) to match your machine.

App id used by install + pidcat:

```text
com.example.piximons
```

Override at runtime:

```bash
ANDROID_APP_ID=com.your.app scripts/android-device-picker.sh
```

And edit the pidcat / `am start` lines in `.zed/tasks.json`.

## Picker keys

**Devices:** ↑↓ · Enter · `n` new AVD · `d` delete · `r` refresh · `q` quit  
**Gradle:** type to filter · ↑↓ · Enter · Ctrl+R refresh · Esc quit  
**iOS:** ↑↓ · Enter (boot/shutdown) · `r` · `q` — uses existing `xcrun simctl` only

## Optional tools

- [pidcat](https://github.com/JakeWharton/pidcat) for colored logcat
- `emulator` + `adb` on `PATH` (from `ANDROID_HOME`)
- Xcode only if you already have it (iOS picker will show an error and wait, it will not install)

## License

MIT
