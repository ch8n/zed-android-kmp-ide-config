#!/usr/bin/env bash
# Debounced Compose preview watcher for Zed.
# Re-renders when the focused Kotlin tab changes or that file is saved.
#
#   scripts/compose-preview-watch.sh
#   COMPOSE_PREVIEW_DEBOUNCE=2 scripts/compose-preview-watch.sh --blueprint
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ZED_WORKTREE_ROOT:-${ZED_DIR:-}}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
  if [ ! -f "$ROOT/gradlew" ]; then
    ROOT="$PWD"
  fi
fi
RENDER="$HERE/compose-preview-zed.sh"
DEBOUNCE="${COMPOSE_PREVIEW_DEBOUNCE:-1.5}"
SEED="${ZED_FILE:-}"

if [ ! -x "$RENDER" ] && [ -f "$RENDER" ]; then
  chmod +x "$RENDER"
fi
if [ ! -f "$RENDER" ]; then
  echo "missing $RENDER" >&2
  exit 1
fi

echo "compose preview watch  root=$ROOT  debounce=${DEBOUNCE}s"
echo "save a .kt file or focus another @Preview file — stop the task to quit"

python3 - "$ROOT" "$RENDER" "$DEBOUNCE" "$SEED" "$@" <<'PY'
import os, re, sqlite3, subprocess, sys, time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
render = sys.argv[2]
debounce = float(sys.argv[3])
seed = sys.argv[4] if len(sys.argv) > 4 else ""
extra = sys.argv[5:]

preview_re = re.compile(
    r"@Preview(?:[\s\S]{0,400}?)@Composable\s+(?:private |internal |public )?fun\s+(\w+)",
    re.M,
)


def has_preview(path: Path) -> bool:
    try:
        return bool(preview_re.search(path.read_text(encoding="utf-8")))
    except OSError:
        return False


def zed_active_kotlin():
    db_root = Path.home() / "Library/Application Support/Zed/db"
    if not db_root.is_dir():
        return None
    sql = """
        SELECT CAST(e.path AS TEXT)
        FROM panes p
        JOIN items i
          ON i.pane_id = p.pane_id AND i.workspace_id = p.workspace_id AND i.active = 1
        JOIN editors e
          ON e.item_id = i.item_id AND e.workspace_id = i.workspace_id
        WHERE p.active = 1
    """
    hits = []
    for db in db_root.glob("*/db.sqlite"):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = con.execute(sql).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for (raw,) in rows:
            if not raw:
                continue
            p = Path(raw)
            if p.suffix in {".kt", ".kts"} and p.is_file():
                try:
                    p.resolve().relative_to(root)
                except ValueError:
                    continue
                hits.append(p)
    return hits[0] if hits else None


def newest_saved_kotlin(after):
    newest = None
    for folder in (root / "app" / "src", root / "src"):
        if not folder.is_dir():
            continue
        for p in folder.rglob("*.kt"):
            if p.name.endswith("_BlueprintPreviews.kt"):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m <= after:
                continue
            if newest is None or m > newest[0]:
                newest = (m, p)
    if newest is None:
        return None
    return newest[1] if has_preview(newest[1]) else None


def file_mtime(path):
    if path is None:
        return 0.0
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


target = None
if seed and Path(seed).suffix in {".kt", ".kts"} and Path(seed).is_file():
    target = Path(seed)
elif (last := root / ".zed" / "compose-preview" / "last-kt").is_file():
    p = Path(last.read_text().strip())
    if p.is_file():
        target = p

last_key = None
pending_at = 0.0 if target is not None else None
busy = False
last_scan = time.time() - 0.1

print(f"seed {target or '(none yet)'}", flush=True)

while True:
    now = time.time()
    focused = zed_active_kotlin()
    if focused is not None and has_preview(focused) and focused != target:
        print(f"focus → {focused}", flush=True)
        target = focused
        pending_at = now
    saved = newest_saved_kotlin(last_scan)
    last_scan = now
    if saved is not None:
        if saved != target:
            print(f"saved → {saved}", flush=True)
            target = saved
        pending_at = now
    elif target is not None:
        key = (str(target), file_mtime(target))
        if last_key is not None and key != last_key and pending_at is None:
            pending_at = now

    if (
        target is not None
        and pending_at is not None
        and not busy
        and (now - pending_at) >= debounce
    ):
        key = (str(target), file_mtime(target))
        pending_at = None
        if key == last_key:
            time.sleep(0.25)
            continue
        busy = True
        print(f"render {target.name} …", flush=True)
        rc = subprocess.call(
            [render, "--file", str(target), *extra],
            cwd=str(root),
        )
        if rc == 0:
            last_key = key
            print(f"ok {target.name}", flush=True)
        else:
            print(f"render failed ({rc}) — will retry after the next change", flush=True)
        busy = False
    time.sleep(0.35)
PY
