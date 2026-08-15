#!/usr/bin/env bash
# Install Zed Android+KMP config: settings, every helper script, all tasks,
# Compose Preview / watch / stability LSP, inspector + recomp agent.
# Usage:
#   ./install.sh [project-dir]
#   ./install.sh --force ~/code/my-app
#   ./install.sh --user-only
#   curl -fsSL https://raw.githubusercontent.com/ch8n/zed-android-kmp-ide-config/main/install.sh | bash -s -- --force [project-dir]
#
# Does not install Xcode, Android SDK, or JDK.
# Optional: Homebrew pidcat, pip Pillow (preview PNG stitch).
set -euo pipefail

REPO_SLUG="ch8n/zed-android-kmp-ide-config"
REPO_URL="https://github.com/${REPO_SLUG}.git"
FORCE=0
DO_USER=1
DO_PROJECT=1
DO_LSP=1
TARGET=""

usage() {
  cat <<EOF
install.sh — Zed Android+KMP: kotlin-lsp, every task + script, Compose Preview/watch/stability, inspector

Usage:  install.sh [--force] [--no-user] [--user-only] [--no-lsp] [project-dir]

  project-dir   Android/KMP repo root (default: current directory)
  --force       overwrite without prompting (still writes .bak)
  --no-user     do not write ~/.config/zed/settings.json
  --user-only   only user settings + Zed extension (skip project files)
  --no-lsp      skip installing the compose-stability Zed extension

Installs:
  • ~/.config/zed/settings.json   (kotlin-lsp, compose-stability, JDK/SDK env)
  • <project>/.zed/tasks.json     (Preview, watch, inspector, stability, pidcat, pickers)
  • <project>/.zed/settings.json
  • <project>/scripts/            (every helper, including recomp-agent + init Gradle)
  • <project>/.gitignore + .zed/compose-preview no-index (via compose-preview-clean.sh --ensure)
  • Zed extension compose-stability (hover / diagnostics / inlays)
  • optional: pidcat (brew), Pillow (pip --user) for preview PNG stitch

Does not install or update Xcode / Android SDK / JDK.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -f|--force) FORCE=1; shift ;;
    --no-user) DO_USER=0; shift ;;
    --user-only) DO_PROJECT=0; DO_USER=1; shift ;;
    --no-lsp) DO_LSP=0; shift ;;
    --) shift; break ;;
    -*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
    *) TARGET="$1"; shift ;;
  esac
done

if [ -z "$TARGET" ]; then
  TARGET="$PWD"
fi
if [ "$DO_PROJECT" -eq 1 ]; then
  TARGET="$(cd "$TARGET" && pwd)"
fi

USER_ZED="${HOME}/.config/zed"
USER_SETTINGS="${USER_ZED}/settings.json"

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

zed_extensions_root() {
  if [ "$(uname -s)" = "Darwin" ]; then
    printf '%s' "${HOME}/Library/Application Support/Zed/extensions"
  else
    printf '%s' "${XDG_DATA_HOME:-$HOME/.local/share}/zed/extensions"
  fi
}

SRC=""
CLEANUP_SRC=""
resolve_src() {
  local here
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$here/.zed/tasks.json" ] && [ -f "$here/user/settings.json" ]; then
      SRC="$here"
      return 0
    fi
  fi
  if need_cmd git; then
    CLEANUP_SRC="$(mktemp -d "${TMPDIR:-/tmp}/zed-android-kmp-ide-config.XXXXXX")"
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

install_file() {
  local src="$1" dest="$2"
  [ -f "$src" ] || return 0
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ]; then
    if ! confirm "overwrite $dest ?"; then
      echo "  skip    $dest"
      return 0
    fi
    backup "$dest"
  fi
  cp "$src" "$dest"
  echo "  wrote   $dest"
}

install_user_settings() {
  mkdir -p "$USER_ZED"
  if [ -e "$USER_SETTINGS" ]; then
    if ! confirm "overwrite ${USER_SETTINGS} (kotlin-lsp, compose-stability, docks, fonts, env) ?"; then
      echo "skip user settings (kept existing)"
      return 0
    fi
    backup "$USER_SETTINGS"
  fi
  cp "$SRC/user/settings.json" "$USER_SETTINGS"
  echo "  wrote   $USER_SETTINGS"
  echo "  kotlin  kotlin-lsp + compose-stability; fwcd kotlin-language-server off"
  echo "  gradle  groovy + java extensions (Gradle LSP / JDTLS)"
  echo "  ext     auto_install html, kotlin, toml, groovy, java"
}

install_project() {
  mkdir -p "$TARGET/.zed" "$TARGET/scripts"

  install_file "$SRC/.zed/tasks.json" "$TARGET/.zed/tasks.json"
  install_file "$SRC/.zed/settings.json" "$TARGET/.zed/settings.json"

  echo "  scripts (preview, watch, inspector, stability, pickers, recomp-agent)"
  local rel
  while IFS= read -r rel; do
    rel="${rel#./}"
    [ -n "$rel" ] || continue
    install_file "$SRC/scripts/$rel" "$TARGET/scripts/$rel"
  done < <(
    cd "$SRC/scripts"
    find . -type f \
      ! -path './.*' \
      ! -name '*.pyc' \
      ! -path '*/__pycache__/*'
  )
  # Nested paths (recomp-agent/build.sh) plus top-level helpers.
  find "$TARGET/scripts" -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod +x {} + 2>/dev/null || true

  if [ -f "$TARGET/scripts/compose-preview-clean.sh" ]; then
    chmod +x "$TARGET/scripts/compose-preview-clean.sh" 2>/dev/null || true
    env ZED_WORKTREE_ROOT="$TARGET" "$TARGET/scripts/compose-preview-clean.sh" --ensure || true
    echo "  preview  no-index + gitignore + zed-exit cleaner"
  else
    merge_gitignore
  fi

  if [ -d "$SRC/zed-extension/compose-stability" ]; then
    mkdir -p "$TARGET/zed-extension/compose-stability/src"
    install_file "$SRC/zed-extension/compose-stability/extension.toml" \
      "$TARGET/zed-extension/compose-stability/extension.toml"
    install_file "$SRC/zed-extension/compose-stability/Cargo.toml" \
      "$TARGET/zed-extension/compose-stability/Cargo.toml"
    [ -f "$SRC/zed-extension/compose-stability/Cargo.lock" ] && \
      install_file "$SRC/zed-extension/compose-stability/Cargo.lock" \
        "$TARGET/zed-extension/compose-stability/Cargo.lock"
    [ -f "$SRC/zed-extension/compose-stability/src/lib.rs" ] && \
      install_file "$SRC/zed-extension/compose-stability/src/lib.rs" \
        "$TARGET/zed-extension/compose-stability/src/lib.rs"
    [ -f "$SRC/zed-extension/compose-stability/extension.wasm" ] && \
      install_file "$SRC/zed-extension/compose-stability/extension.wasm" \
        "$TARGET/zed-extension/compose-stability/extension.wasm"
    echo "  wrote   $TARGET/zed-extension/compose-stability/"
  fi
}

install_compose_stability_extension() {
  local wasm="$SRC/zed-extension/compose-stability/extension.wasm"
  local toml="$SRC/zed-extension/compose-stability/extension.toml"
  if [ ! -f "$toml" ]; then
    echo "  skip    compose-stability extension (source missing)"
    return 0
  fi
  if [ ! -f "$wasm" ]; then
    echo "  warn    no prebuilt extension.wasm — build with:"
    echo "          rustup target add wasm32-wasip2 && cargo build --target wasm32-wasip2 --release"
    echo "          (must be wasip2 / component, not wasip1)"
    return 0
  fi

  local root dest
  root="$(zed_extensions_root)"
  dest="${root}/installed/compose-stability"
  mkdir -p "$dest"
  if [ -e "$dest/extension.wasm" ] && ! confirm "overwrite Zed extension $dest ?"; then
    echo "  skip    $dest"
  else
    [ -e "$dest/extension.wasm" ] && backup "$dest/extension.wasm"
    cp "$toml" "$dest/extension.toml"
    cp "$wasm" "$dest/extension.wasm"
    echo "  wrote   $dest/extension.toml"
    echo "  wrote   $dest/extension.wasm"
  fi

  if ! need_cmd python3; then
    echo "  warn    python3 missing — could not register extension in index.json"
    return 0
  fi
  python3 - "$root" <<'PY'
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
index_path = root / "index.json"
entry = {
    "manifest": {
        "id": "compose-stability",
        "name": "Compose Stability",
        "version": "0.1.0",
        "schema_version": 1,
        "description": "Hover, diagnostics, and inlay hints from Compose compiler stability reports.",
        "repository": None,
        "authors": ["zed-android-kmp-ide-config"],
        "lib": {"kind": "Rust", "version": "0.7.0"},
        "themes": [],
        "icon_themes": [],
        "languages": [],
        "grammars": {},
        "language_servers": {
            "compose-stability": {
                "language": "Kotlin",
                "languages": ["Kotlin"],
                "language_ids": {},
                "code_action_kinds": None,
            }
        },
        "context_servers": {},
        "slash_commands": {},
        "snippets": None,
        "capabilities": [],
    },
    "dev": False,
}
if index_path.is_file():
    data = json.loads(index_path.read_text())
else:
    data = {"extensions": {}, "themes": {}, "icon_themes": {}, "languages": {}}
data.setdefault("extensions", {})["compose-stability"] = entry
index_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"  wrote   {index_path} (compose-stability registered)")
PY
}

print_tasks() {
  local tasks="$1"
  [ -f "$tasks" ] || return 0
  echo
  echo "Zed tasks registered (Cmd+Shift+R):"
  if need_cmd python3; then
    python3 - "$tasks" <<'PY'
import json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_text()
# settings/tasks may have // comments — strip line comments for this file (tasks.json is pure JSON)
data = json.loads(raw)
for i, t in enumerate(data, 1):
    print(f"  {i:2}. {t.get('label','?')}  →  {t.get('command','')} {' '.join(t.get('args') or [])}")
PY
  else
    grep -o '"label": "[^"]*"' "$tasks" | sed 's/"label": /  • /'
  fi
}

merge_gitignore() {
  local gi="$TARGET/.gitignore"
  local block
  block=$(cat <<'EOF'
.zed/compose-preview.md
.zed/compose-preview.html
.zed/compose-preview/
.zed/generated/
EOF
)
  mkdir -p "$TARGET"
  if [ ! -f "$gi" ]; then
    printf '%s\n' "$block" >"$gi"
    echo "  wrote   $gi (preview output ignores)"
    return 0
  fi
  local line added=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if ! grep -qxF "$line" "$gi"; then
      printf '%s\n' "$line" >>"$gi"
      added=1
    fi
  done <<<"$block"
  if [ "$added" -eq 1 ]; then
    echo "  updated $gi (preview output ignores)"
  else
    echo "  ok      $gi already ignores preview output"
  fi
}

maybe_pillow() {
  if ! need_cmd python3; then
    echo "Pillow    skipped (python3 missing)"
    return 0
  fi
  if python3 -c "from PIL import Image" >/dev/null 2>&1; then
    echo "Pillow    ok"
    return 0
  fi
  if confirm "Pillow not found (needed to stitch Compose Preview _all.png). pip install --user Pillow ?"; then
    python3 -m pip install --user Pillow
    echo "Pillow    installed"
  else
    echo "Pillow    skipped — Compose Preview gallery stitch will fail"
  fi
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
  if need_cmd python3; then
    echo "python3   ok  $(command -v python3)"
  else
    echo "python3   MISSING — preview watch, inspector, stability TUI, and LSP need python3"
  fi
  if [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/java" ]; then
    echo "JAVA_HOME ok  $JAVA_HOME"
  elif [ -x /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin/java ]; then
    echo "JAVA_HOME default Homebrew openjdk@17 is present"
  else
    echo "JAVA_HOME not found — edit user/settings.json and .zed/settings.json"
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
  if [ "$DO_PROJECT" -eq 1 ]; then
    echo "target    $TARGET"
  else
    echo "target    (user settings + Zed extension)"
  fi
  resolve_src
  echo "source    $SRC"
  if [ "$DO_USER" -eq 1 ]; then
    install_user_settings
  fi
  if [ "$DO_PROJECT" -eq 1 ]; then
    install_project
    maybe_pidcat
    maybe_pillow
    print_tasks "$TARGET/.zed/tasks.json"
  fi
  if [ "$DO_LSP" -eq 1 ]; then
    echo
    echo "Compose stability LSP (Zed extension)"
    install_compose_stability_extension
  fi
  check_env
  if [ -n "$CLEANUP_SRC" ]; then
    rm -rf "$CLEANUP_SRC"
  fi
  echo
  echo "done."
  echo "1. Restart Zed (or zed: reload window) so kotlin-lsp + compose-stability attach."
  echo "2. Cmd+Shift+R → task list:"
  echo "     Compose Preview / Preview watch / Blueprint,"
  echo "     Stability report, Layout Inspector, Devices, pidcat, Gradle, iOS."
  echo "3. Compose Preview writes .zed/compose-preview/_all.png (zoomable PNG tab)."
  echo "   Drag that tab to the right pane once; later runs reuse it."
  echo "4. Compose: Stability report once, then hover @Composable names."
  echo "edit JAVA_HOME / ANDROID_HOME in ~/.config/zed/settings.json if needed"
  echo "app id is read from Gradle applicationId (override ANDROID_APP_ID)"
}

main
