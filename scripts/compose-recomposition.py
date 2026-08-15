#!/usr/bin/env python3
"""Sidecar helpers for Compose recomposition counts (no app source).

Library used by interactive_inspector_recomp.py. Running this file (or
compose-recomposition.sh) opens the inspector+counts TUI.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEX = os.path.join(HERE, "recomp-agent.dex")
SNAP = "cache/pixi_recomp.tsv"
CMD = "cache/pixi_recomp.cmd"
NAME_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")
JDWP_PORT = 18731


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    try:
        input("\npress enter to close… ")
    except EOFError:
        pass
    sys.exit(code)


def run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)


def resolve_pkg() -> str:
    env = os.environ.get("ANDROID_APP_ID") or os.environ.get("PIDCAT_PACKAGE")
    if env:
        return env.strip()
    helper = os.path.join(HERE, "android-app-id.sh")
    p = run(["bash", helper, ROOT])
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    die("could not resolve applicationId")


def app_pid(pkg: str) -> str | None:
    p = run(["adb", "shell", "pidof", pkg])
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return p.stdout.strip().split()[0]


def write_cmd(pkg: str, cmd: str) -> None:
    root = data_dir(pkg)
    path = f"{root}/cache/pixi_recomp.cmd"
    run(["adb", "shell", f"run-as {pkg} sh -c 'printf %s {cmd} > {path}'"])


def data_dir(pkg: str) -> str:
    p = run(["adb", "shell", "run-as", pkg, "pwd"])
    path = (p.stdout or "").strip()
    return path or f"/data/data/{pkg}"


def inject(pkg: str, pid: str) -> None:
    sys.path.insert(0, HERE)
    from jdwp_min import inject_recomp_agent

    if not os.path.isfile(DEX):
        die(f"missing {DEX} — run scripts/recomp-agent/build.sh")
    dex_bytes = open(DEX, "rb").read()
    run(["adb", "forward", f"tcp:{JDWP_PORT}", f"jdwp:{pid}"])
    try:
        inject_recomp_agent("127.0.0.1", JDWP_PORT, dex_bytes)
    finally:
        run(["adb", "forward", "--remove", f"tcp:{JDWP_PORT}"])


def pull_snapshot(pkg: str):
    """Return rows, or None if the read failed / raced a write (keep last counts)."""
    p = run(["adb", "exec-out", "run-as", pkg, "cat", SNAP], timeout=4.0)
    text = p.stdout or ""
    if p.returncode != 0 or "v=1" not in text:
        return None
    rows: list[tuple[str, str, int]] = []
    for line in text.splitlines():
        if not line or line.startswith("v="):
            continue
        if "\t" not in line:
            continue
        name, n_s = line.rsplit("\t", 1)
        try:
            n = int(n_s)
        except ValueError:
            continue
        m = NAME_RE.match(name)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip(), n))
        else:
            rows.append((name, "", n))
    return rows


if __name__ == "__main__":
    inspector = os.path.join(HERE, "interactive_inspector_recomp.py")
    os.execv(sys.executable, [sys.executable, inspector])
