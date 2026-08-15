# zed-android+kmp-ide-config

Zed as a light IDE for **Android + Kotlin + KMP/KMM**: JetBrains `kotlin-lsp`, one shared JDK with Gradle, tasks, and interactive TUI pickers (devices, Gradle tasks, iOS sims).

> GitHub repo slug is `zed-android-kmp-ide-config` (`+` is not allowed in GitHub names).

Interactive pickers open as **center editor tabs**. Failures stay visible (`hide: on_success` + Enter to close).

## Install

From a clone:

```bash
./install.sh --force /path/to/your-android-or-kmp-project
```

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/ch8n/zed-android-kmp-ide-config/main/install.sh | bash -s -- --force /path/to/your-project
```

| Flag | Meaning |
|---|---|
| `--force` | overwrite project files (writes `.bak` first); also overwrite user settings |
| `--no-user` | skip `~/.config/zed/settings.json` |
| `--user-only` | only write user settings, skip project copy |

Does **not** install Xcode, Android SDK, or a JDK. If Homebrew is present, it can install **pidcat**.

Reload Zed (`task: spawn` / Cmd+Shift+R). Restart Zed once so `kotlin-lsp` attaches.

## Kotlin language server

Zed’s default fwcd `kotlin-language-server` red-squiggles Android/KMP (`R`, Compose, Gradle types). This config:

1. Auto-installs the official **Kotlin** extension (`auto_install_extensions.kotlin`)
2. Forces **`kotlin-lsp`** (JetBrains) and disables fwcd:

```json
"languages": {
  "Kotlin": {
    "language_servers": ["kotlin-lsp", "!kotlin-language-server"]
  }
}
```

3. Passes the **same** `JAVA_HOME` / `ANDROID_HOME` into the LSP process and the terminal so Gradle does not spawn a second daemon.

Edit those paths in `user/settings.json` and `.zed/settings.json` if your machine differs.

## What’s included

| Path | Role |
|---|---|
| `user/settings.json` | Full user Zed settings (kotlin-lsp, docks, fonts, theme, extensions, JDK/SDK env) |
| `.zed/settings.json` | Project overlay: kotlin-lsp + terminal env |
| `.zed/tasks.json` | Assemble, install, pidcat, pickers, tests, clean |
| `scripts/android-device-picker.sh` | ↑↓ AVD/USB: start/stop, logcat, new/delete AVD |
| `scripts/gradle-task-picker.sh` | Type-to-filter all Gradle tasks, Enter to run |
| `scripts/ios-simulator-picker.sh` | ↑↓ existing sims only — **never** installs Xcode |

### User settings copied from this machine

- Panels: git / debugger / project / outline **left**; agent **right**; terminal dock **left**
- UI font 16 / buffer 15 / One Dark
- Auto-install extensions: `html`, `kotlin`, `toml`
- `kotlin-lsp` + `!kotlin-language-server`
- Terminal + LSP env: Homebrew OpenJDK 17 + `android-commandlinetools`

## Tasks

- **Android: Devices & emulators** — center tab
- **Gradle: Tasks (filter & run)** — center tab
- **iOS: Simulators** — center tab (will not install Xcode)
- **Emulator: Start small_phone (lite)** — center tab
- pidcat variants stay in the terminal dock
- assemble / install / tests / clean reuse the existing terminal

## Env you should edit

Defaults match Homebrew on Apple Silicon:

- `JAVA_HOME` → `/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` → `/opt/homebrew/share/android-commandlinetools`

App id used by install + pidcat: `com.example.piximons`

```bash
ANDROID_APP_ID=com.your.app scripts/android-device-picker.sh
```

And edit the pidcat / `am start` lines in `.zed/tasks.json`.

## Picker keys

**Devices:** ↑↓ · Enter · `n` new AVD · `d` delete · `r` refresh · `q` quit  
**Gradle:** type to filter · ↑↓ · Enter · Ctrl+R refresh · Esc quit  
**iOS:** ↑↓ · Enter (boot/shutdown) · `r` · `q` — existing `xcrun simctl` only

## Optional tools

- [pidcat](https://github.com/JakeWharton/pidcat) for colored logcat
- `emulator` + `adb` on `PATH` (from `ANDROID_HOME`)
- Xcode only if you already have it

## License

MIT
