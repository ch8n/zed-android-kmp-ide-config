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

OUT_MD="${ROOT}/.zed/compose-preview.md"
OUT_DIR="${ROOT}/.zed/compose-preview"
mkdir -p "$OUT_DIR" "$(dirname "$OUT_MD")" "$GEN_ROOT"

FILTER_PROPS=()
NAMES=()

if [ "$ALL" -eq 0 ] && [ -n "$FILE" ] && [ -f "$FILE" ]; then
  case "$FILE" in
    *.kt|*.kts) ;;
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
./gradlew \
  --init-script "$INIT" \
  --no-configuration-cache \
  ":${MODULE}:composePreviewDiscover" \
  ":${MODULE}:composePreviewRender" \
  "${FILTER_PROPS[@]}" \
  --quiet

RENDERS="${ROOT}/${MODULE}/build/compose-previews"
if [ ! -d "$RENDERS" ]; then
  echo "no output at $RENDERS" >&2
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

python3 - "$RENDERS" "$OUT_DIR" "$OUT_MD" "${NAMES[@]+${NAMES[@]}}" <<'PY'
import sys, shutil
from pathlib import Path

renders = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
md_path = Path(sys.argv[3])
names = sys.argv[4:]

pngs = sorted(renders.rglob("*.png"))
if names:
    keys = [n.lower() for n in names]
    keys += [n.lower() + "_blueprint" for n in names]
    pngs = [p for p in pngs if any(k in p.stem.lower() for k in keys)]

lines = [
    "# Compose Preview",
    "",
    "Host render (Robolectric). No app Gradle edits. Blueprint files live under `.zed/generated/`.",
    "",
]
if not pngs:
    lines += ["_No PNGs matched._", ""]
for p in pngs:
    dest = out_dir / p.name
    shutil.copy2(p, dest)
    rel = dest.relative_to(md_path.parent)
    kind = "blueprint" if "_blueprint" in p.stem.lower() else "preview"
    lines += [f"## {p.stem}", "", f"_{kind}_", "", f"![{p.stem}]({rel.as_posix()})", ""]

md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {md_path}  ({len(pngs)} png)")
for p in pngs:
    print(f"  {p.name}")
PY

echo
echo "open    $OUT_MD"
if command -v zed >/dev/null 2>&1; then
  zed "$OUT_MD" || true
fi
echo
echo "done. markdown preview of that tab shows the images"
echo "press Enter to close this task tab"
read -r _ || true
