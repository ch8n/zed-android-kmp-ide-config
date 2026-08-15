#!/usr/bin/env python3
"""Emit Blueprint companion @Preview sources outside the app tree.

Writes to:
  <out-root>/<module-name>/<package-path>/<Stem>_BlueprintPreviews.kt

Default out-root is <repo>/.zed/generated/blueprint
An init script adds that folder as a debug source set and injects the
Blueprint Maven dep — no build.gradle edits.

Private @Preview functions are copied (body duplicated), not called.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PREVIEW_ANN = re.compile(r"@Preview(?:LightDark|FontScale|ScreenSizes)?\b")
FUN_HEAD = re.compile(
    r"((?:@[^\n]+\n)+)"
    r"(@Composable\n)"
    r"((?:private |internal |public )?fun )(\w+)(\([^)]*\)(?:\s*:\s*[^{\n]+)?\s*)\{",
    re.MULTILINE,
)
PKG = re.compile(r"^package\s+([\w.]+)", re.M)
IMPORT = re.compile(r"^import\s+\S+", re.M)
BLUEPRINT_IMPORT = (
    "import uk.co.gusward.blueprint.compose.preview.preview.BlueprintPreview"
)


def matching_brace_end(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        elif c == '"':
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
        i += 1
    raise ValueError("unbalanced braces")


def extract_previews(src: str) -> list[dict]:
    out = []
    for m in FUN_HEAD.finditer(src):
        anns = m.group(1)
        if "@Preview" not in anns and not PREVIEW_ANN.search(anns):
            continue
        name = m.group(4)
        if name.endswith("_Blueprint"):
            continue
        open_idx = m.end() - 1
        try:
            close_idx = matching_brace_end(src, open_idx)
        except ValueError:
            continue
        body = src[open_idx + 1 : close_idx]
        if "BlueprintPreview" in body:
            continue
        out.append(
            {
                "anns": anns.rstrip() + "\n",
                "composable": m.group(2),
                "vis_fun": m.group(3).replace("private ", "internal "),
                "name": name,
                "sig": m.group(5),
                "body": body,
            }
        )
    return out


def module_name_for(kt: Path) -> str | None:
    for parent in kt.parents:
        if parent.name == "src":
            return parent.parent.name
    return None


def repo_root_for(kt: Path) -> Path | None:
    for parent in kt.parents:
        if (parent / "gradlew").is_file():
            return parent
    return None


def emit_file(kt: Path, out_root: Path) -> Path | None:
    text = kt.read_text(encoding="utf-8")
    previews = extract_previews(text)
    if not previews:
        return None
    module = module_name_for(kt) or "app"
    pkg_m = PKG.search(text)
    pkg_line = pkg_m.group(0) if pkg_m else "package generated.blueprint"
    pkg = pkg_m.group(1) if pkg_m else "generated.blueprint"
    imports = IMPORT.findall(text)
    if BLUEPRINT_IMPORT not in imports:
        imports.append(BLUEPRINT_IMPORT)
    dest = out_root / module / Path(*pkg.split(".")) / f"{kt.stem}_BlueprintPreviews.kt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        pkg_line + "\n",
        "\n".join(imports) + "\n",
        "\n// Generated — not part of the app source tree.\n",
    ]
    for p in previews:
        chunks.append(
            f"{p['anns']}{p['composable']}{p['vis_fun']}{p['name']}_Blueprint{p['sig']}{{\n"
            f"  BlueprintPreview {{\n"
            f"{p['body'].rstrip()}\n"
            f"  }}\n"
            f"}}\n"
        )
    dest.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="default: <repo>/.zed/generated/blueprint",
    )
    args = ap.parse_args()
    out_root = args.out_root
    if out_root is None:
        repo = repo_root_for(args.files[0].resolve())
        if repo is None:
            print("could not find gradlew; pass --out-root", file=sys.stderr)
            return 2
        out_root = repo / ".zed" / "generated" / "blueprint"
    wrote = 0
    for f in args.files:
        if not f.is_file():
            print(f"missing {f}", file=sys.stderr)
            return 2
        dest = emit_file(f, out_root)
        if dest:
            print(dest)
            wrote += 1
    if wrote == 0:
        print("no @Preview functions found to wrap", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
