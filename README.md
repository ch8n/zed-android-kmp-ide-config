# zed-android+kmp-ide-config

Zed as a light IDE for **Android + Kotlin + KMP/KMM**: JetBrains `kotlin-lsp`, one shared JDK with Gradle, Compose Preview / stability / Layout Inspector, and interactive TUI pickers (devices, Gradle tasks, iOS sims, logcat).

> GitHub repo slug is `zed-android-kmp-ide-config` (`+` is not allowed in GitHub names).

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
| `--user-only` | only user settings + Zed extension, skip project copy |
| `--no-lsp` | skip installing the compose-stability Zed extension |

`install.sh` copies **every** file under `scripts/` (including `recomp-agent/` and `recomp-agent.dex`), writes `.zed/tasks.json` + `.zed/settings.json`, runs `compose-preview-clean.sh --ensure` (gitignore + no-index + Zed-exit cleaner), installs user Zed settings, registers the **compose-stability** extension, and offers **pidcat** + **Pillow** (needed to stitch preview PNGs).

Does **not** install Xcode, Android SDK, or a JDK.

Reload Zed (`zed: reload window`). Restart once so `kotlin-lsp` and `compose-stability` attach. Then **Cmd+Shift+R** for the task list.

## Features

### Kotlin language server

Zed’s default fwcd `kotlin-language-server` red-squiggles Android/KMP (`R`, Compose, Gradle types). This config:

1. Auto-installs the official **Kotlin** extension (`auto_install_extensions.kotlin`)
2. Forces **`kotlin-lsp`** (JetBrains) and disables fwcd:

```json
"languages": {
  "Kotlin": {
    "language_servers": ["kotlin-lsp", "compose-stability", "!kotlin-language-server"]
  }
}
```

3. Passes the **same** `JAVA_HOME` / `ANDROID_HOME` into the LSP process and the terminal so Gradle does not spawn a second daemon.
4. Caps **kotlin-lsp only** at **768 MB** (`_JAVA_OPTIONS=-Xmx768m` on `lsp.kotlin-lsp.binary.env` — not on the terminal). Restart Zed after install.

Edit those paths in `user/settings.json` and `.zed/settings.json` if your machine differs.

### Gradle in Zed

Zed has no standalone “Gradle” extension. This config stacks:

| Piece | Extension | What you get |
|---|---|---|
| `*.gradle` | **groovy** | syntax for Groovy build scripts |
| `*.gradle.kts` | **kotlin** (`kotlin-lsp`) | Kotlin DSL highlighting + completion |
| `gradle/libs.versions.toml` | **toml** | version-catalog highlighting |
| Gradle model / `build.gradle` intelligence | **java** (Microsoft Gradle LSP + JDTLS) | plugin-aware completions, wrapper import |

`install.sh` auto-installs `groovy` and `java` next to `kotlin` / `toml`.

**One daemon rule:** terminal + kotlin-lsp + Gradle wrapper stay on **OpenJDK 17** (`JAVA_HOME` in settings). JDTLS *prefers* 21+; if it fails to start, install `openjdk@21` and point **only** `lsp.jdtls.settings.java_home` at 21 — do **not** change terminal `JAVA_HOME`.

Use **Gradle: Stop daemons** / `./gradlew --stop` if RAM climbs.

### Compose Preview (host PNG, no app plugin)

Renders `@Preview` on the host via Yuri’s `ee.schimke.composeai.preview` **init script**. The app’s `build.gradle.kts` / version catalog stay clean.

| Task | What it does |
|---|---|
| **Compose: Preview (this file)** | Robolectric PNGs for `@Preview` in the focused `.kt` |
| **Compose: Preview + Blueprint (this file)** | same + Blueprint measurement overlays |
| **Compose: Preview all + Blueprint** | every preview in the module (slow first run) |
| **Compose: Preview watch** | stays running; debounce 1.5s; re-renders on **save** or focused `@Preview` file |
| **Compose: Preview clean** | delete leftover per-preview PNGs (keeps `_all.png`) |

Output is **one** gallery: `.zed/compose-preview/_all.png` (Zed PNG tabs zoom; SVG preview does not). Per-preview PNGs stay in Gradle `build/` and are **not** copied next to `_all.png`.

If that image tab is already open, the script **overwrites in place** and does not open a second tab. Drag `_all.png` to the right pane once.

#### No extra files on new projects

`compose-preview-zed.sh`, watch, and `install.sh` all call `scripts/compose-preview-clean.sh --ensure`. That is enough for a fresh repo:

- writes `.nomedia`, `.metadata_never_index`, `CACHEDIR.TAG` under `.zed/compose-preview/` and `.zed/generated/` (Spotlight / Photos / Android galleries skip them)
- appends `.zed/compose-preview*` and `.zed/generated/` to the project `.gitignore` if missing
- starts one Zed-exit waiter per project (cleans leftover PNGs a few seconds after Zed is gone)

You do **not** add those markers by hand. Flags: `--ensure` · `--intermediates` · `--purge` · `--when-zed-exits`.

Preview tasks use the **bottom dock** (`reveal: no_focus`) and **hide on success**. Watch stays open until you stop it.

Needs **Python 3.9+** and **Pillow**. Gradle must be able to resolve `ee.schimke.composeai.preview` (applied only by `scripts/compose-preview.init.gradle`). Pin note: the init script forces `androidx.core` 1.18.0 so compileSdk 36 / AGP 9.0 still check AAR metadata.

```bash
scripts/compose-preview-zed.sh              # focused file via $ZED_FILE
scripts/compose-preview-zed.sh --blueprint
scripts/compose-preview-zed.sh --all
COMPOSE_PREVIEW_DEBOUNCE=2 scripts/compose-preview-watch.sh
scripts/compose-preview-clean.sh --ensure   # also run by install + every preview
```

Zed has **no HTML preview tab**. Markdown/SVG/PNG only.

### Compose compiler stability

**Compose: Stability report** writes skippable / unstable params (`*/compose_compiler/*-composables.txt`) without editing `build.gradle`. The **compose-stability** Zed extension hovers `@Composable` names, warns on unstable / not skippable, and shows inlays.

`install.sh` copies prebuilt `zed-extension/compose-stability/extension.wasm` (`wasm32-wasip2`) into Zed’s extension index. `--no-lsp` skips that.

1. Run **Compose: Stability report** once.
2. Reload Zed. Hover composables.

Rebuild wasm: `rustup target add wasm32-wasip2 && cargo build --target wasm32-wasip2 --release`.

### Layout Inspector + live recomposition

**Android: Layout Inspector** — tree + per-composable counts (`c` toggles counts). Talks to a **debug APK** over JDWP (`scripts/jdwp_min.py` + `recomp-agent.dex`). No app source change.

### Devices, logcat, iOS, Gradle pickers

| Task | Role |
|---|---|
| **Android: Devices & emulators** | ↑↓ AVD/USB: start/stop, logcat, new/delete AVD |
| **Emulator: Start small_phone (lite)** | 1 GB / 2 cores / no snapshot (edit AVD name in the task) |
| **Android: Install & Launch Debug App** | `:app:installDebug` then `am start` |
| **Logcat: pidcat** (app / emulator / device / errors) | colored; tag + multi-select levels |
| **Gradle: Tasks (filter & run)** | type-to-filter all Gradle tasks |
| **iOS: Simulators** | existing `xcrun simctl` only — **never** installs Xcode |
| **Android: Unit Tests** | `:app:testDebugUnitTest` |
| **Gradle: Clean** / **Gradle: Stop daemons** | wrapper tasks |

## What’s installed

| Path | Role |
|---|---|
| `user/settings.json` | User Zed settings (kotlin-lsp, docks, fonts, theme, extensions, JDK/SDK env) |
| `.zed/settings.json` | Project overlay: kotlin-lsp + terminal env |
| `.zed/tasks.json` | Every task listed above |
| `scripts/android-device-picker.sh` | Device / AVD TUI |
| `scripts/android-install-launch.sh` | installDebug + launch |
| `scripts/android-app-id.sh` | Reads `applicationId` (`app/`, `androidApp/`, `composeApp/`) |
| `scripts/pidcat-app.sh` / `pidcat-app.py` | Colored logcat |
| `scripts/gradle-task-picker.sh` | Gradle task TUI |
| `scripts/ios-simulator-picker.sh` | Simulator TUI |
| `scripts/interactive_inspector_recomp.py` | Layout inspector TUI |
| `scripts/jdwp_min.py` | JDWP helper for inspector |
| `scripts/recomp-agent.dex` + `recomp-agent/` | Recomposition agent (prebuilt + source) |
| `scripts/compose-preview-zed.sh` | Host `@Preview` → `_all.png` |
| `scripts/compose-preview-watch.sh` | Debounced watch (Python 3.9) |
| `scripts/compose-preview-clean.sh` | `--ensure` (no-index + gitignore + waiter); `--intermediates`; `--purge`; `--when-zed-exits` |
| `scripts/compose-preview.init.gradle` | Applies preview plugin + Blueprint **without** app Gradle edits |
| `scripts/compose-blueprint-previews.py` | Blueprint companions under `.zed/generated/` |
| `scripts/compose-stability-report.sh` / `.py` | Stability TUI |
| `scripts/compose-reports.init.gradle` | Compose compiler reports via init script |
| `scripts/compose-stability-lsp.py` | Tiny LSP: hover + diagnostics + inlays |
| `scripts/compose-recomposition.sh` / `.py` | CLI recomposition helper |
| `zed-extension/compose-stability/` | Zed extension that starts the stability LSP |

Generated (gitignored by install): `.zed/compose-preview/`, `.zed/generated/`.

### User settings copied from this machine

- Panels: git / debugger / project / outline **left**; agent **right**; terminal dock **left**
- UI font 16 / buffer 15 / One Dark
- Auto-install extensions: `html`, `kotlin`, `toml`, `groovy`, `java`
- `kotlin-lsp` + `compose-stability` + `!kotlin-language-server`
- Terminal + LSP env: Homebrew OpenJDK 17 + `android-commandlinetools`

## Tasks (Cmd+Shift+R)

Interactive pickers and inspector open as a **center** tab and **close on success**. Compose Preview one-shots stay in the **dock** and hide on success. **Compose: Preview watch** stays until you stop it.

- **Android: Layout Inspector** — tree + per-composable counts (`c` on/off)
- **Compose: Preview clean** — delete leftover per-preview PNGs (keep `_all.png`)
- **Compose: Preview watch** — auto refresh on save / focused `@Preview` file (1.5s debounce)
- **Compose: Preview (this file)** — `_all.png` for previews in the active tab
- **Compose: Preview + Blueprint (this file)** — plus measurement overlays
- **Compose: Preview all + Blueprint** — whole module
- **Compose: Stability report** — skippable / unstable (`i` issues/all)
- **Android: Install & Launch Debug App**
- **Logcat: pidcat** (app / emulator / device / errors)
- **Android: Devices & emulators**
- **Gradle: Tasks (filter & run)**
- **iOS: Simulators**
- **Emulator: Start small_phone (lite)**
- **Android: Unit Tests** / **Gradle: Clean** / **Gradle: Stop daemons**

## Env you should edit

Defaults match Homebrew on Apple Silicon:

- `JAVA_HOME` → `/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` → `/opt/homebrew/share/android-commandlinetools`

App id is read from the project's `applicationId`. Override with `ANDROID_APP_ID` if needed.

```bash
scripts/android-app-id.sh
scripts/pidcat-app.sh -t OverlayService -l WE
```

Module for preview: `ANDROID_MODULE=app` (default). Debounce: `COMPOSE_PREVIEW_DEBOUNCE=1.5`.

## Picker keys

**Devices:** ↑↓ · Enter · `n` new AVD · `d` delete · `r` refresh · `q` quit  
**Gradle:** type to filter · ↑↓ · Enter · Ctrl+R refresh · Esc quit  
**iOS:** ↑↓ · Enter (boot/shutdown) · `r` · `q` — existing `xcrun simctl` only  
**Logcat:** type tag (empty = all, `apple|banana` = contains any) · Enter · Space toggle levels · Enter start · q cancel  
**Inspector:** `c` toggle recomposition counts  
**Stability:** `i` issues / all

## Optional tools

- **pidcat** — `install.sh` offers `brew install pidcat`
- **Pillow** — `install.sh` offers `python3 -m pip install --user Pillow` (preview gallery stitch)
- `emulator` + `adb` on `PATH` (from `ANDROID_HOME`)
- Xcode only if you already have it
- Python 3.9+ (macOS system Python is fine)

## License

MIT
