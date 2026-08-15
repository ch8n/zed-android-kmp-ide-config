#!/usr/bin/env bash
# Render Compose @Preview PNGs without editing the app Gradle files.
#
# Uses scripts/compose-preview.init.gradle to:
#   • apply ee.schimke.composeai.preview (do not add it to the app)
#   • add Blueprint as debugImplementation
#   • compile generated companions from .zed/generated/blueprint/
#
# Usage:
#   scripts/compose-preview-zed.sh
#   scripts/compose-preview-zed.sh --blueprint
#   scripts/compose-preview-zed.sh --all
#   ANDROID_MODULE=app
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ZED_WORKTREE_ROOT:-${ZED_DIR:-}}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
  if [ ! -f "$ROOT/gradlew" ]; then
    ROOT="$PWD"
  fi
fi
cd "$ROOT"

MODULE="${ANDROID_MODULE:-app}"
BLUEPRINT=0
ALL=0
FILE="${ZED_FILE:-}"
INIT="$HERE/compose-preview.init.gradle"
GEN_ROOT="${ROOT}/.zed/generated/blueprint"

while [ $# -gt 0 ]; do
  case "$1" in
    --blueprint|-b) BLUEPRINT=1; shift ;;
    --all) ALL=1; shift ;;
    --file) FILE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ ! -x "./gradlew" ]; then
  echo "no ./gradlew in $ROOT" >&2
  exit 1
fi
if [ ! -f "$INIT" ]; then
  echo "missing init script $INIT" >&2
  exit 1
fi

preview_names_in() {
  python3 - "$1" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
pat = re.compile(
    r"@Preview(?:[\s\S]{0,400}?)@Composable\s+(?:private |internal |public )?fun\s+(\w+)",
    re.M,
)
seen = []
for m in pat.finditer(text):
    n = m.group(1)
    if n not in seen:
        seen.append(n)
print("\n".join(seen))
PY
}

OUT_DIR="${ROOT}/.zed/compose-preview"
LAST_KT="${OUT_DIR}/last-kt"
mkdir -p "$OUT_DIR" "$GEN_ROOT"
# Markers + .gitignore + zed-exit cleaner (no per-project setup).
if [ -f "$HERE/compose-preview-clean.sh" ]; then
  chmod +x "$HERE/compose-preview-clean.sh" 2>/dev/null || true
  env ZED_WORKTREE_ROOT="$ROOT" "$HERE/compose-preview-clean.sh" --ensure || true
fi

# If the preview PNG (or any non-Kotlin tab) is focused, ZED_FILE is that
# path and the task used to exit instantly — looks like "nothing happened".
if [ "$ALL" -eq 0 ]; then
  case "${FILE:-}" in
    *.kt|*.kts) ;;
    *)
      if [ -f "$LAST_KT" ]; then
        FILE="$(cat "$LAST_KT")"
        echo "active tab is not Kotlin; using last previewed file: $FILE"
      fi
      ;;
  esac
fi

FILTER_PROPS=()
NAMES=()

if [ "$ALL" -eq 0 ] && [ -n "$FILE" ] && [ -f "$FILE" ]; then
  case "$FILE" in
    *.kt|*.kts) printf '%s\n' "$FILE" >"$LAST_KT" ;;
    *)
      echo "current tab is not Kotlin: $FILE" >&2
      exit 1
      ;;
  esac
  while IFS= read -r n; do
    [ -n "$n" ] && NAMES+=("$n")
  done < <(preview_names_in "$FILE")
  if [ "${#NAMES[@]}" -eq 0 ]; then
    echo "no @Preview functions in $FILE" >&2
    exit 1
  fi
  GLOB=""
  for n in "${NAMES[@]}"; do
    [ -n "$GLOB" ] && GLOB="${GLOB},"
    GLOB="${GLOB}*${n}*"
  done
  FILTER_PROPS+=("-PcomposePreview.filter=${GLOB}")
  echo "previews in file: ${NAMES[*]}"
  if [ "$BLUEPRINT" -eq 1 ]; then
    echo "generating Blueprint companions → ${GEN_ROOT} (not in app src)"
    python3 "$HERE/compose-blueprint-previews.py" --out-root "$GEN_ROOT" "$FILE"
  fi
else
  echo "rendering all discovered @Preview functions (slow first time)"
  if [ "$BLUEPRINT" -eq 1 ]; then
    echo "generating Blueprint companions → ${GEN_ROOT}"
    find "${MODULE}/src" -name '*.kt' ! -name '*_BlueprintPreviews.kt' -print0 \
      | xargs -0 python3 "$HERE/compose-blueprint-previews.py" --out-root "$GEN_ROOT" || true
  fi
fi

echo "gradle  --init-script compose-preview.init.gradle :${MODULE}:composePreviewRender"
if ! ./gradlew \
  --init-script "$INIT" \
  --no-configuration-cache \
  ":${MODULE}:composePreviewDiscover" \
  ":${MODULE}:composePreviewRender" \
  "${FILTER_PROPS[@]}"; then
  echo "gradle preview render FAILED" >&2
  exit 1
fi

RENDERS="${ROOT}/${MODULE}/build/compose-previews"
if [ ! -d "$RENDERS" ]; then
  echo "no output at $RENDERS" >&2
  exit 1
fi

# Same path forever. If Zed already has an ImageView tab for it, we only
# overwrite bytes (same inode). `zed path` would open a second tab.
mkdir -p "$OUT_DIR"
SHEET="$OUT_DIR/_all.png"

zed_image_tab_open() {
  python3 - "$1" <<'PY'
import sqlite3, sys
from pathlib import Path

want = str(Path(sys.argv[1]).resolve())
db_root = Path.home() / "Library/Application Support/Zed/db"
if not db_root.is_dir():
    print("no")
    raise SystemExit(0)
for db in db_root.glob("*/db.sqlite"):
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = con.execute(
            """
            SELECT 1
            FROM image_viewers iv
            JOIN items i
              ON i.item_id = iv.item_id AND i.workspace_id = iv.workspace_id
            WHERE CAST(iv.image_path AS TEXT) = ?
            LIMIT 1
            """,
            (want,),
        ).fetchone()
        con.close()
        if row:
            print("yes")
            raise SystemExit(0)
    except sqlite3.Error:
        continue
print("no")
PY
}
python3 - "$RENDERS" "$OUT_DIR" "$SHEET" "${NAMES[@]+${NAMES[@]}}" <<'PY'
import os, sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("need Pillow to stitch gallery: python3 -m pip install --user Pillow", file=sys.stderr)
    sys.exit(1)

renders = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
sheet = Path(sys.argv[3])
names = sys.argv[4:]

pngs = sorted(
    p
    for p in renders.rglob("*.png")
    if p.name not in ("_all.png",)
)
if names:
    keys = [n.lower() for n in names]
    keys += [n.lower() + "_blueprint" for n in names]
    pngs = [p for p in pngs if any(k in p.stem.lower() for k in keys)]

if not pngs:
    print("no PNGs matched", file=sys.stderr)
    sys.exit(1)

# Stitch from Gradle output. Do not copy per-preview PNGs into .zed/
# (those show up in Photos / gallery apps).
copied = list(pngs)
images = [Image.open(p).convert("RGBA") for p in copied]
# Drop leftover copies from older runs.
for leftover in out_dir.glob("*.png"):
    if leftover.name != sheet.name:
        leftover.unlink(missing_ok=True)
for leftover in out_dir.glob("*.png.tmp"):
    leftover.unlink(missing_ok=True)

pad, label_h, gap = 24, 36, 28
max_w = max(im.width for im in images)
total_h = pad + sum(label_h + im.height + gap for im in images)
width = max_w + pad * 2

bg = Image.new("RGB", (width, total_h), (30, 30, 30))
draw = ImageDraw.Draw(bg)
try:
    font = ImageFont.truetype("Menlo.ttc", 16)
except OSError:
    font = ImageFont.load_default()

y = pad
for src, im in zip(copied, images):
    kind = "blueprint" if "_blueprint" in src.stem.lower() else "preview"
    draw.text((pad, y + 8), f"{src.stem}  ·  {kind}", fill=(230, 230, 230), font=font)
    y += label_h
    x = pad + (max_w - im.width) // 2
    if im.mode == "RGBA":
        bg.paste(im, (x, y), im)
    else:
        bg.paste(im, (x, y))
    y += im.height + gap
    im.close()

# Overwrite in place so an already-open ImageView keeps the same file.
sheet.parent.mkdir(parents=True, exist_ok=True)
with open(sheet, "wb") as fh:
    bg.save(fh, "PNG")
    fh.flush()
    os.fsync(fh.fileno())
os.utime(sheet, None)
print(sheet)
print(f"png gallery {len(copied)} previews → {sheet.name} ({width}x{total_h})", file=sys.stderr)
PY

if [ ! -f "$SHEET" ]; then
  echo "failed to write $SHEET" >&2
  exit 1
fi

if [ "$(zed_image_tab_open "$SHEET")" = "yes" ]; then
  echo "swapped content in existing image tab: $SHEET"
else
  if command -v zed >/dev/null 2>&1; then
    echo "no image tab yet — opening $SHEET (drag to the right pane once)"
    zed -a -e "$SHEET" || true
  else
    echo "open $SHEET in a right pane; later runs overwrite the same file" >&2
  fi
fi
echo "zoom: cmd+= / cmd+- or trackpad"
