#!/usr/bin/env python3
"""Colored logcat: type a tag (empty = all tags), multi-select levels, Enter to start.

Homebrew pidcat 2.1.0 is broken on Python 3 — this uses `adb logcat -v threadtime`.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import termios
import time
import tty
from typing import List, Optional, Set

LEVELS = ("V", "D", "I", "W", "E", "F")
LEVEL_LABEL = {
    "V": "Verbose",
    "D": "Debug",
    "I": "Info",
    "W": "Warn",
    "E": "Error",
    "F": "Fatal",
}
LEVEL_STYLE = {
    "V": "\033[37m",
    "D": "\033[34m",
    "I": "\033[32m",
    "W": "\033[33m",
    "E": "\033[31m",
    "F": "\033[35;1m",
}

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
REV = "\033[7m"
HIDE = "\033[?25l"
SHOW = "\033[?25h"

THREADTIME = re.compile(
    r"^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(\d+)\s+(\d+)\s+([VDIWEF])\s+"
    r"(.+?):\s(.*)$"
)


def env_term() -> None:
    term = os.environ.get("TERM") or ""
    if term in ("", "dumb", "unknown"):
        os.environ["TERM"] = "xterm-256color"
    os.environ.setdefault("CLICOLOR", "1")
    os.environ.setdefault("FORCE_COLOR", "1")
    os.environ.setdefault("COLORTERM", "truecolor")
    home = os.environ.get(
        "ANDROID_HOME", "/opt/homebrew/share/android-commandlinetools"
    )
    os.environ["PATH"] = (
        os.path.join(home, "platform-tools") + os.pathsep + os.environ.get("PATH", "")
    )


def adb_base(args: argparse.Namespace) -> List[str]:
    cmd = ["adb"]
    if args.serial:
        cmd.extend(["-s", args.serial])
    if args.device:
        cmd.append("-d")
    if args.emulator:
        cmd.append("-e")
    return cmd


def read_key() -> str:
    fd = sys.stdin.fileno()
    ch = os.read(fd, 1)
    if ch == b"\x03":
        return "ctrlc"
    if ch == b"\x1b":
        rest = b""
        os.set_blocking(fd, False)
        try:
            rest = os.read(fd, 3) or b""
        except OSError:
            rest = b""
        finally:
            os.set_blocking(fd, True)
        if rest.startswith(b"[A"):
            return "up"
        if rest.startswith(b"[B"):
            return "down"
        return "esc"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b" ":
        return "space"
    if ch in (b"a", b"A"):
        return "all"
    if ch in (b"q", b"Q"):
        return "quit"
    return "other"


def read_tag() -> Optional[str]:
    """None = cancel. '' = no tag filter."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(f"{CYAN}Logcat filter — tag{RESET}\n")
    sys.stdout.write(
        f"{DIM}Tag contains (empty = all). Multiple: apple|banana. Esc/Ctrl+C cancel.{RESET}\n\n"
    )
    sys.stdout.write("tag: ")
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return None
    if line is None:
        return None
    return line.strip()


def pick_levels(preselect: Optional[Set[str]] = None) -> Optional[Set[str]]:
    """Space toggles. Enter starts. Empty / all selected = every level."""
    selected: Set[str] = set(preselect) if preselect else set(LEVELS)
    idx = 0
    fd = sys.stdin.fileno()
    orig = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(HIDE)
        while True:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(f"{CYAN}Logcat filter — levels{RESET}\n")
            sys.stdout.write(
                f"{DIM}↑↓  Space toggle  a all  Enter start  q cancel{RESET}\n\n"
            )
            for i, lv in enumerate(LEVELS):
                mark = "[x]" if lv in selected else "[ ]"
                line = f"{mark}  {lv}  {LEVEL_LABEL[lv]}"
                if i == idx:
                    sys.stdout.write(f"  {REV} {line} {RESET}\n")
                else:
                    sys.stdout.write(f"    {line}\n")
            if not selected or selected == set(LEVELS):
                hint = "selected: all"
            else:
                hint = "selected: " + ",".join(lv for lv in LEVELS if lv in selected)
            sys.stdout.write(f"\n{DIM}{hint}{RESET}\n")
            sys.stdout.flush()
            k = read_key()
            if k == "up":
                idx = (idx - 1) % len(LEVELS)
            elif k == "down":
                idx = (idx + 1) % len(LEVELS)
            elif k == "space":
                lv = LEVELS[idx]
                if lv in selected:
                    selected.discard(lv)
                else:
                    selected.add(lv)
            elif k == "all":
                selected = set(LEVELS) if selected != set(LEVELS) else set()
            elif k == "enter":
                return selected or set(LEVELS)
            elif k in ("quit", "esc", "ctrlc"):
                return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, orig)
        sys.stdout.write(SHOW + "\033[2J\033[H")
        sys.stdout.flush()


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def resolve_package(cli: Optional[str] = None) -> str:
    if cli:
        return cli
    for key in ("ANDROID_APP_ID", "PIDCAT_PACKAGE"):
        val = os.environ.get(key)
        if val:
            return val
    helper = os.path.join(script_dir(), "android-app-id.sh")
    if os.path.isfile(helper):
        try:
            out = subprocess.check_output(["bash", helper], stderr=subprocess.STDOUT)
            pkg = out.decode("utf-8", "replace").strip().splitlines()[-1].strip()
            if pkg:
                return pkg
        except subprocess.CalledProcessError as exc:
            err = exc.output.decode("utf-8", "replace") if exc.output else str(exc)
            raise SystemExit(err or "could not resolve applicationId") from exc
    raise SystemExit("could not resolve applicationId (set ANDROID_APP_ID)")


def pids_of(adb: List[str], pkg: str) -> List[str]:
    try:
        raw = subprocess.check_output(
            adb + ["shell", "pidof", pkg], stderr=subprocess.DEVNULL
        ).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return []
    return [p for p in raw.replace("\r", "").split() if p.isdigit()]


def parse_levels_flag(raw: Optional[str]) -> Optional[Set[str]]:
    if not raw:
        return None
    out: Set[str] = set()
    for ch in raw.upper():
        if ch in LEVELS:
            out.add(ch)
    return out or None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Colored logcat: tag (empty=all) then multi-select levels"
    )
    p.add_argument("-c", "--clear", action="store_true")
    p.add_argument("-d", "--device", action="store_true")
    p.add_argument("-e", "--emulator", action="store_true")
    p.add_argument("-s", "--serial")
    p.add_argument(
        "-l",
        "--levels",
        help="preselect levels, e.g. E or WE (skips level picker)",
    )
    p.add_argument("-t", "--tag", help="tag filter; empty string = all tags")
    p.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="skip builder: all tags, all levels",
    )
    p.add_argument(
        "package",
        nargs="?",
        default=None,
        help="applicationId (default: from this project's Gradle file)",
    )
    return p.parse_args()


def choose_filter(args: argparse.Namespace) -> Optional[tuple[str, Set[str]]]:
    """Return (tag, levels). tag '' = all tags. None = cancel."""
    if args.all:
        return "", set(LEVELS)

    tag: Optional[str]
    if args.tag is not None:
        tag = args.tag.strip()
    elif args.levels:
        # e.g. errors task: -l E → all tags, those levels, no prompts
        tag = ""
    elif sys.stdin.isatty():
        tag = read_tag()
        if tag is None:
            return None
    else:
        tag = ""

    pre = parse_levels_flag(args.levels)
    if pre is not None:
        return tag, pre
    if not sys.stdin.isatty():
        return tag, set(LEVELS)
    levels = pick_levels()
    if levels is None:
        return None
    return tag, levels


def color_line(ts: str, level: str, tag: str, msg: str) -> str:
    st = LEVEL_STYLE.get(level, "")
    tag_w = tag[-22:].rjust(22)[:22]
    return f"{DIM}{ts[-12:]}{RESET} {st}{level}{RESET} {BOLD}{tag_w}{RESET} {st}{msg}{RESET}"


def parse_tag_patterns(raw: str) -> List[str]:
    """'apple|banana' → contains-any, case-insensitive. Empty → no tag filter."""
    return [p.strip().lower() for p in (raw or "").split("|") if p.strip()]


def accept(
    line_tag: str, level: str, patterns: List[str], want_levels: Set[str]
) -> bool:
    if level not in want_levels:
        return False
    if patterns:
        hay = line_tag.lower()
        if not any(p in hay for p in patterns):
            return False
    return True


def start_logcat(adb: List[str], pids: List[str]) -> subprocess.Popen[str]:
    cmd = adb + ["logcat", "-v", "threadtime"]
    for pid in pids:
        cmd.extend(["--pid", pid])
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def main() -> int:
    env_term()
    if not shutil.which("adb"):
        print("adb not on PATH", file=sys.stderr)
        print("Press Enter to close.")
        try:
            input()
        except EOFError:
            pass
        return 1

    args = parse_args()
    try:
        pkg = resolve_package(args.package)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        print("Press Enter to close.")
        try:
            input()
        except EOFError:
            pass
        return 1

    adb = adb_base(args)
    chosen = choose_filter(args)
    if chosen is None:
        return 0
    tag, levels = chosen
    patterns = parse_tag_patterns(tag)

    if args.clear:
        subprocess.call(adb + ["logcat", "-c"])

    lv = "".join(x for x in LEVELS if x in levels)
    tag_disp = "|".join(patterns) if patterns else "*"
    print(f"package={pkg}  tag contains {tag_disp}  levels={lv}")
    print("Ctrl+C to stop.\n")

    last: List[str] = []
    proc: Optional[subprocess.Popen[str]] = None
    try:
        while True:
            pids = pids_of(adb, pkg)
            if pids != last:
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                last = pids
                if not pids:
                    print(f"waiting for process {pkg} ...", flush=True)
                    proc = None
                else:
                    print(f"attached pids {', '.join(pids)}", flush=True)
                    proc = start_logcat(adb, pids)
            if proc is None or proc.stdout is None:
                time.sleep(1)
                continue
            line = proc.stdout.readline()
            if line == "":
                if proc.poll() is not None:
                    last = []
                    proc = None
                    time.sleep(0.4)
                continue
            raw = line.replace("\r", "").rstrip("\n")
            m = THREADTIME.match(raw)
            if not m:
                continue
            ts, _pid, _tid, level, line_tag, msg = m.groups()
            line_tag = line_tag.strip()
            if not accept(line_tag, level, patterns, levels):
                continue
            print(color_line(ts, level, line_tag, msg), flush=True)
    except KeyboardInterrupt:
        if proc is not None and proc.poll() is None:
            proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
