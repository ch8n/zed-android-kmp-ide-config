# zed-android+kmp-ide-config

Zed as a light IDE for **Android + Kotlin + KMP/KMM**: JetBrains `kotlin-lsp`, one shared JDK with Gradle, tasks, and interactive TUI pickers (devices, Gradle tasks, iOS sims).

> GitHub repo slug is `zed-android-kmp-ide-config` (`+` is not allowed in GitHub names).

Every registered task opens as a **center editor tab** (`use_new_terminal` + `reveal_target: center`) and **closes when it succeeds** (`hide: on_success`). Failures stay visible until you press Enter.

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

`install.sh` copies **every** helper under `scripts/`, writes `.zed/tasks.json` + `.zed/settings.json`, installs user Zed settings, and registers the **compose-stability** extension in Zed (`extension.wasm` → Application Support) so hover / diagnostics / inlays work after a reload.

Does **not** install Xcode, Android SDK, or a JDK. If Homebrew is present, it can install **pidcat**.

Reload Zed (`zed: reload window`). Restart once so `kotlin-lsp` and `compose-stability` attach. Then **Cmd+Shift+R** for the task list.

## Gradle in Zed

Zed has no standalone “Gradle” extension. This config stacks three pieces:

| Piece | Extension | What you get |
|---|---|---|
| `*.gradle` | **groovy** | syntax for Groovy build scripts |
| `*.gradle.kts` | **kotlin** (`kotlin-lsp`) | Kotlin DSL highlighting + completion |
| `gradle/libs.versions.toml` | **toml** | version-catalog highlighting |
| Gradle model / `build.gradle` intelligence | **java** (Microsoft Gradle LSP + JDTLS) | plugin-aware completions, wrapper import |

`install.sh` auto-installs `groovy` and `java` next to `kotlin` / `toml`.

**One daemon rule:** terminal + kotlin-lsp + Gradle wrapper stay on **OpenJDK 17** (`JAVA_HOME` in settings). JDTLS *prefers* 21+; if it fails to start, install `openjdk@21` and point **only** `lsp.jdtls.settings.java_home` at 21 — do **not** change terminal `JAVA_HOME` or you get a second Gradle daemon.

The Java extension may keep a Gradle language-server process warm. Use **Gradle: Stop daemons** / `./gradlew --stop` if RAM climbs.

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
4. Caps **kotlin-lsp only** at **768 MB** (`_JAVA_OPTIONS=-Xmx768m` on `lsp.kotlin-lsp.binary.env` — not on the terminal, so `./gradlew` is unchanged). Default IntelliJ vmoptions is `-Xmx2048m`. Restart Zed (or restart `kotlin-lsp`) after install.

Edit those paths in `user/settings.json` and `.zed/settings.json` if your machine differs.

## What’s included

| Path | Role |
|---|---|
| `user/settings.json` | Full user Zed settings (kotlin-lsp, docks, fonts, theme, extensions, JDK/SDK env) |
| `.zed/settings.json` | Project overlay: kotlin-lsp + terminal env |
| `.zed/tasks.json` | Install+launch, pidcat, pickers, tests, clean |
| `scripts/android-device-picker.sh` | ↑↓ AVD/USB: start/stop, logcat, new/delete AVD |
| `scripts/android-install-launch.sh` | `:app:installDebug` then launch (fails if `am start` errors) |
| `scripts/android-app-id.sh` | Reads `applicationId` from this project |
| `scripts/pidcat-app.sh` | Colored logcat: tag (empty=all) then multi-select levels |
| `scripts/gradle-task-picker.sh` | Type-to-filter all Gradle tasks, Enter to run |
| `scripts/ios-simulator-picker.sh` | ↑↓ existing sims only — **never** installs Xcode |
| `scripts/interactive_inspector_recomp.py` | Layout inspector + live recomposition counts (`c` toggles counts; debug APK, no app source) |
| `scripts/compose-stability-report.sh` | Compose compiler stability TUI (skippable / unstable params; no build.gradle edit) |
| `scripts/compose-stability-lsp.py` | Tiny LSP: hover + diagnostics + inlays from those reports |
| `zed-extension/compose-stability/` | Zed extension that starts the LSP for Kotlin |

### User settings copied from this machine

- Panels: git / debugger / project / outline **left**; agent **right**; terminal dock **left**
- UI font 16 / buffer 15 / One Dark
- Auto-install extensions: `html`, `kotlin`, `toml`, `groovy`, `java`
- `kotlin-lsp` + `!kotlin-language-server`
- Terminal + LSP env: Homebrew OpenJDK 17 + `android-commandlinetools`

## Tasks

- **Android: Layout Inspector** — tree + per-composable counts (`c` on/off)
- **Compose: Stability report** — compiler skippable/unstable report (`i` issues/all)

### Compose stability in the editor (LSP)

`install.sh` installs the prebuilt `zed-extension/compose-stability/extension.wasm` (must be **wasm32-wasip2** / component) and registers it in Zed’s extension index. Settings already list `compose-stability` next to `kotlin-lsp`.

Then:

1. Run **Compose: Stability report** once (`*/compose_compiler/*-composables.txt`).
2. Reload Zed. Hover `@Composable` names: skippable + param table; warning if unstable / not skippable; inlays on the function and params.

`--no-lsp` skips the extension copy. Rebuild wasm with `rustup target add wasm32-wasip2 && cargo build --target wasm32-wasip2 --release` (wasip1 is rejected by Zed).
- **Android: Install & Launch Debug App** — `:app:installDebug` + launch
- **Logcat: pidcat** (app / emulator / device / errors) — colored
- **Android: Devices & emulators**
- **Gradle: Tasks (filter & run)**
- **iOS: Simulators** (will not install Xcode)
- **Emulator: Start small_phone (lite)**
- **Android: Unit Tests** / **Gradle: Clean** / **Gradle: Stop daemons**

## Env you should edit

Defaults match Homebrew on Apple Silicon:

- `JAVA_HOME` → `/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` → `/opt/homebrew/share/android-commandlinetools`

App id is read from the project's `applicationId` in Gradle (`app/`, `androidApp/`, or `composeApp/`). Override with `ANDROID_APP_ID` if needed.

```bash
scripts/android-app-id.sh
scripts/pidcat-app.sh -t OverlayService -l WE
```

## Picker keys

**Devices:** ↑↓ · Enter · `n` new AVD · `d` delete · `r` refresh · `q` quit  
**Gradle:** type to filter · ↑↓ · Enter · Ctrl+R refresh · Esc quit  
**iOS:** ↑↓ · Enter (boot/shutdown) · `r` · `q` — existing `xcrun simctl` only  
**Logcat:** type tag (empty = all, `apple|banana` = contains any) · Enter · Space toggle levels · Enter start · q cancel

## Optional tools

- Colored logcat via `scripts/pidcat-app.py` — tag (empty=all), then multi-select levels. App id from Gradle.
- `emulator` + `adb` on `PATH` (from `ANDROID_HOME`)
- Xcode only if you already have it

## License

MIT
