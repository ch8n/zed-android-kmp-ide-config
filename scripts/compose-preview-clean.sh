#!/usr/bin/env bash
# Compose Preview hygiene: no-index markers, gitignore, leftover PNG cleanup.
# Called by compose-preview-zed.sh / watch / install.sh so new projects
# do not need hand-created .nomedia files.
#
#   scripts/compose-preview-clean.sh                 # intermediates only
#   scripts/compose-preview-clean.sh --ensure        # markers + gitignore + zed-exit waiter
#   scripts/compose-preview-clean.sh --intermediates
#   scripts/compose-preview-clean.sh --purge
#   scripts/compose-preview-clean.sh --when-zed-exits
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ZED_WORKTREE_ROOT:-${ZED_DIR:-}}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
  if [ ! -f "$ROOT/gradlew" ]; then
    ROOT="$PWD"
  fi
fi

OUT="${ROOT}/.zed/compose-preview"
GEN="${ROOT}/.zed/generated"
MODE="intermediates"

while [ $# -gt 0 ]; do
  case "$1" in
    --ensure) MODE="ensure"; shift ;;
    --intermediates) MODE="intermediates"; shift ;;
    --purge|--all) MODE="purge"; shift ;;
    --when-zed-exits) MODE="wait-zed"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

mark_no_index() {
  local dir="$1"
  mkdir -p "$dir"
  : >"$dir/.nomedia"
  : >"$dir/.metadata_never_index"
  [ -f "$dir/CACHEDIR.TAG" ] || printf '%s\n' 'Signature: 8a477f597d28d172789f06886806bc55' >"$dir/CACHEDIR.TAG"
}

merge_gitignore() {
  local gi="$ROOT/.gitignore"
  local line added=0
  local block
  block=$(cat <<'EOF'
.zed/compose-preview.md
.zed/compose-preview.html
.zed/compose-preview/
.zed/generated/
EOF
)
  if [ ! -f "$gi" ]; then
    printf '%s\n' "$block" >"$gi"
    echo "wrote $gi (preview output ignores)"
    return 0
  fi
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if ! grep -qxF "$line" "$gi"; then
      printf '%s\n' "$line" >>"$gi"
      added=1
    fi
  done <<<"$block"
  if [ "$added" -eq 1 ]; then
    echo "updated $gi (preview output ignores)"
  fi
}

start_zed_exit_waiter() {
  local lock="$OUT/.zed-exit-clean.pid"
  mkdir -p "$OUT"
  if [ -f "$lock" ]; then
    local old
    old="$(cat "$lock" 2>/dev/null || true)"
    if [ -n "${old:-}" ] && kill -0 "$old" 2>/dev/null; then
      return 0
    fi
  fi
  nohup env ZED_WORKTREE_ROOT="$ROOT" "$HERE/compose-preview-clean.sh" --when-zed-exits \
    >/dev/null 2>&1 &
}

ensure() {
  mark_no_index "$OUT"
  mark_no_index "$GEN"
  merge_gitignore
  start_zed_exit_waiter
}

clean_intermediates() {
  mark_no_index "$OUT"
  [ -d "$OUT" ] || return 0
  local f n=0
  for f in "$OUT"/*.png "$OUT"/*.png.tmp; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
      _all.png) continue ;;
    esac
    rm -f "$f"
    n=$((n + 1))
  done
  echo "cleaned $n intermediate preview png(s) in $OUT"
}

purge_all() {
  mark_no_index "$OUT"
  [ -d "$OUT" ] || return 0
  find "$OUT" -type f \
    ! -name '.nomedia' \
    ! -name '.metadata_never_index' \
    ! -name 'CACHEDIR.TAG' \
    ! -name 'last-kt' \
    ! -name '.zed-exit-clean.pid' \
    -delete
  echo "purged preview outputs in $OUT (kept no-index + last-kt)"
}

zed_running() {
  pgrep -x zed >/dev/null 2>&1 || pgrep -f '/Zed.app/Contents/MacOS/zed' >/dev/null 2>&1
}

wait_zed_exit() {
  local lock="$OUT/.zed-exit-clean.pid"
  mkdir -p "$OUT"
  if [ -f "$lock" ]; then
    local old
    old="$(cat "$lock" 2>/dev/null || true)"
    if [ -n "${old:-}" ] && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null; then
      echo "zed-exit cleaner already running pid $old"
      return 0
    fi
  fi
  echo $$ >"$lock"
  local gone=0
  while true; do
    if zed_running; then
      gone=0
    else
      gone=$((gone + 1))
      if [ "$gone" -ge 3 ]; then
        clean_intermediates
        rm -f "$lock"
        return 0
      fi
    fi
    sleep 2
  done
}

case "$MODE" in
  ensure) ensure ;;
  intermediates) clean_intermediates ;;
  purge) purge_all ;;
  wait-zed) wait_zed_exit ;;
esac
