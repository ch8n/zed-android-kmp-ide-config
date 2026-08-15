#!/usr/bin/env python3
"""Colored logcat for one app package.

Homebrew pidcat 2.1.0 is broken on Python 3 (print(bytes) so ANSI never
reaches the terminal; filter() iterators; old `ps` regex). Use
`adb logcat -v color --pid` instead.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

PKG_DEFAULT = "com.example.piximons"


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
    plat = os.path.join(home, "platform-tools")
    os.environ["PATH"] = plat + os.pathsep + os.environ.get("PATH", "")


def adb_base(args: argparse.Namespace) -> list[str]:
    cmd = ["adb"]
    if args.serial:
        cmd.extend(["-s", args.serial])
    if args.device:
        cmd.append("-d")
    if args.emulator:
        cmd.append("-e")
    return cmd


def run_out(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode(
            "utf-8", "replace"
        )
    except subprocess.CalledProcessError:
        return ""


def pids_of(adb: list[str], pkg: str) -> list[str]:
    raw = run_out(adb + ["shell", "pidof", pkg]).replace("\r", "").strip()
    return [p for p in raw.split() if p.isdigit()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Colored logcat for the app package")
    p.add_argument("-c", "--clear", action="store_true")
    p.add_argument("-d", "--device", action="store_true")
    p.add_argument("-e", "--emulator", action="store_true")
    p.add_argument("-s", "--serial")
    p.add_argument("-l", "--min-level", default="V")
    p.add_argument("package", nargs="?", default=os.environ.get("PIDCAT_PACKAGE", PKG_DEFAULT))
    return p.parse_args()


def main() -> int:
    env_term()
    if not shutil.which("adb"):
        print("adb not on PATH", file=sys.stderr)
        return 1

    args = parse_args()
    adb = adb_base(args)
    pkg = args.package
    level = (args.min_level or "V").upper()[:1]
    pri = f"*:{level}"

    if args.clear:
        subprocess.call(adb + ["logcat", "-c"])

    print(f"logcat color  package={pkg}  min={level}", file=sys.stderr)
    last_pids: list[str] = []
    proc: subprocess.Popen[bytes] | None = None

    try:
        while True:
            pids = pids_of(adb, pkg)
            if pids != last_pids:
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                last_pids = pids
                if not pids:
                    print(f"waiting for process {pkg} ...", file=sys.stderr)
                    time.sleep(1)
                    continue
                cmd = adb + ["logcat", "-v", "color", "-s", pri]
                for pid in pids:
                    cmd.extend(["--pid", pid])
                print(f"attached pids {', '.join(pids)}", file=sys.stderr)
                proc = subprocess.Popen(cmd)
            if proc is None:
                time.sleep(1)
                continue
            code = proc.poll()
            if code is not None:
                last_pids = []
                time.sleep(0.4)
                continue
            time.sleep(1)
    except KeyboardInterrupt:
        if proc is not None and proc.poll() is None:
            proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
