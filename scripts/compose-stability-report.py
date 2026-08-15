#!/usr/bin/env python3
"""Interactive Compose compiler stability report (project-agnostic)."""
from __future__ import annotations

import curses
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

FUN_HEAD = re.compile(
    r"^(?P<flags>(?:(?:restartable|skippable|readonly|inline|fun)\s+)*)"
    r"fun\s+(?P<name>[A-Za-z0-9_.<>-]+)\s*\("
)
PARAM = re.compile(
    r"^\s*(?P<stab>stable|unstable|runtime)\s+(?P<rest>.+?)\s*$"
)
SCHEME = re.compile(r'\s*scheme\("[^"]*"\)\s*')


@dataclass
class Param:
    stability: str
    text: str


@dataclass
class Comp:
    name: str
    flags: str
    restartable: bool
    skippable: bool
    inline: bool
    params: list[Param] = field(default_factory=list)
    source: str = ""

    @property
    def simple(self) -> str:
        return (self.name or "").rsplit(".", 1)[-1]

    @property
    def issue(self) -> bool:
        if any(p.stability == "unstable" for p in self.params):
            return True
        if (
            self.restartable
            and not self.skippable
            and not self.inline
            and not self.simple.startswith("remember")
        ):
            return True
        return False

    @property
    def summary(self) -> str:
        bits = []
        if self.restartable:
            bits.append("restartable")
        bits.append("skippable" if self.skippable else "NOT skippable")
        if self.inline:
            bits.append("inline")
        uns = [p.text.split(":")[0].strip() for p in self.params if p.stability == "unstable"]
        if uns:
            bits.append("unstable: " + ", ".join(uns[:4]))
        return "  ".join(bits)


def parse_composables_txt(text: str) -> list[Comp]:
    items: list[Comp] = []
    cur: Comp | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            cur = None
            continue
        stripped = SCHEME.sub(" ", line).strip()
        m = FUN_HEAD.search(stripped)
        if m:
            flags = (m.group("flags") or "") + " " + line
            name = m.group("name")
            short = name.rsplit(".", 1)[-1]
            if short.startswith("<get-") or "Preview" in short:
                cur = None
                continue
            cur = Comp(
                name=name,
                flags=flags,
                restartable="restartable" in flags,
                skippable="skippable" in flags,
                inline="inline" in flags,
            )
            items.append(cur)
            continue
        if cur is None:
            continue
        pm = PARAM.match(line)
        if pm:
            cur.params.append(Param(pm.group("stab"), pm.group("rest").strip()))
    return items


def find_reports(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, names in os.walk(root):
        base = os.path.basename(dirpath)
        if base in {".git", ".gradle", ".idea", ".zed"}:
            dirnames[:] = []
            continue
        if "compose_compiler" not in dirpath.replace("\\", "/"):
            continue
        for n in names:
            if n.endswith("-composables.txt"):
                out.append(os.path.join(dirpath, n))
    return sorted(out)


def load_all(root: str) -> list[Comp]:
    items: list[Comp] = []
    seen = set()
    for path in find_reports(root):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for c in parse_composables_txt(text):
            key = (c.name, tuple((p.stability, p.text) for p in c.params))
            if key in seen:
                continue
            seen.add(key)
            items.append(c)
    return items


def index_sources(root: str) -> dict[str, tuple[str, int]]:
    hit: dict[str, tuple[str, int]] = {}
    skip = {"build", ".gradle", ".git", ".idea", ".zed"}
    decl = re.compile(r"fun\s+([A-Za-z0-9_]+)\s*\(")
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for n in names:
            if not n.endswith(".kt"):
                continue
            path = os.path.join(dirpath, n)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                m = decl.search(line)
                if not m:
                    continue
                name = m.group(1)
                chunk = "".join(lines[max(0, i - 12) : i])
                if "@Composable" not in chunk:
                    continue
                hit.setdefault(name, (path, i))
    return hit


def jump_to_ide(file_path: str, line_num: int) -> str:
    target = f"{file_path}:{line_num}"
    if subprocess.run(["which", "zed"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.Popen(["zed", target])
        return f"Opened {os.path.basename(file_path)}:{line_num} in Zed"
    if subprocess.run(["which", "code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.Popen(["code", "-g", target])
        return f"Opened {os.path.basename(file_path)}:{line_num} in VS Code"
    subprocess.Popen(["open", file_path])
    return f"Opened {os.path.basename(file_path)}"


def run_tui(stdscr, root: str, items: list[Comp], sources: dict[str, tuple[str, int]]):
    curses.curs_set(1)
    curses.use_default_colors()
    stdscr.nodelay(False)
    stdscr.timeout(200)
    stdscr.keypad(True)
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)

    query = ""
    issues_only = True
    cursor = 0
    scroll = 0
    status = (
        f"{len(items)} composables from compiler reports. "
        "Type to filter  [i] issues/all  [Enter] Zed  [q] quit"
    )

    def filtered() -> list[Comp]:
        q = query.lower()
        out = []
        for c in items:
            if issues_only and not c.issue:
                continue
            blob = (c.name + " " + c.summary).lower()
            if q and q not in blob:
                continue
            out.append(c)
        out.sort(key=lambda c: (not c.issue, c.name.lower()))
        return out

    while True:
        h, w = stdscr.getmaxyx()
        rows = filtered()
        if rows:
            cursor = max(0, min(cursor, len(rows) - 1))
        else:
            cursor = 0
        view_h = max(1, h - 5)
        if cursor < scroll:
            scroll = cursor
        elif cursor >= scroll + view_h:
            scroll = cursor - view_h + 1

        stdscr.erase()
        mode = "issues" if issues_only else "all"
        header = f" [Compose stability] [{mode}]  {len(rows)}/{len(items)}  filter: {query}█"
        stdscr.addstr(0, 0, header[: w - 1].ljust(w - 1), curses.A_REVERSE | curses.A_BOLD)
        hint = " restartable+NOT skippable or unstable params first. [i] toggle  [Enter] source"
        stdscr.addstr(1, 0, hint[: w - 1], curses.A_DIM)

        for row in range(view_h):
            idx = scroll + row
            if idx >= len(rows):
                break
            c = rows[idx]
            mark = "!" if c.issue else " "
            line = f" {mark} {c.name}   {c.summary}"
            y = row + 2
            attr = curses.A_NORMAL
            if idx == cursor:
                attr = curses.color_pair(1) | curses.A_BOLD
            elif c.issue:
                attr = curses.color_pair(2)
            else:
                attr = curses.color_pair(3)
            try:
                stdscr.addstr(y, 0, line[: w - 1].ljust(w - 1), attr)
            except curses.error:
                pass

        detail_y = h - 2
        if rows:
            sel = rows[cursor]
            extras = []
            for p in sel.params:
                extras.append(f"{p.stability} {p.text}")
            detail = " | ".join(extras) if extras else "(no params / defaults only)"
            try:
                stdscr.addstr(
                    detail_y,
                    0,
                    detail[: w - 1].ljust(w - 1),
                    curses.color_pair(4),
                )
            except curses.error:
                pass
        try:
            stdscr.addstr(h - 1, 0, f" {status}"[: w - 1].ljust(w - 1), curses.A_BOLD)
        except curses.error:
            pass
        stdscr.refresh()

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            break
        if key in (-1,):
            continue
        if key in (ord("q"), 27):
            break
        if key in (ord("i"), ord("I")):
            issues_only = not issues_only
            cursor = 0
            continue
        if key in (curses.KEY_BACKSPACE, 127, 8):
            query = query[:-1]
            cursor = 0
            continue
        if key == curses.KEY_UP:
            cursor = max(0, cursor - 1)
            continue
        if key == curses.KEY_DOWN:
            cursor = min(max(0, len(rows) - 1), cursor + 1)
            continue
        if key in (curses.KEY_ENTER, 10, 13):
            if not rows:
                continue
            name = rows[cursor].name.rsplit(".", 1)[-1]
            loc = sources.get(name)
            if loc:
                status = jump_to_ide(loc[0], loc[1])
            else:
                status = f"No @Composable fun {name} in project sources"
            continue
        if 32 <= key < 127:
            query += chr(key)
            cursor = 0


def main() -> int:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    reports = find_reports(root)
    if not reports:
        print(
            "No *-composables.txt under */compose_compiler/.\n"
            "The Kotlin compile may have failed, or this module has no Compose compiler plugin.",
            file=sys.stderr,
        )
        try:
            input("\nPress Enter to close… ")
        except EOFError:
            pass
        return 1
    items = load_all(root)
    print(f"parsed {len(items)} composables from {len(reports)} report(s)…", flush=True)
    sources = index_sources(root)
    try:
        curses.wrapper(lambda s: run_tui(s, root, items, sources))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
