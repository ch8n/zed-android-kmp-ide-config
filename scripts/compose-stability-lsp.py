#!/usr/bin/env python3
"""Tiny LSP: Compose compiler stability → hover, diagnostics, inlay hints.

Reads *-composables.txt under */compose_compiler/ (same reports as
compose-stability-report.sh). Does not compile. No app source changes.

Zed: register via the compose-stability extension + Kotlin language_servers.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "compose_stability_report", os.path.join(HERE, "compose-stability-report.py")
)
_csr = importlib.util.module_from_spec(_spec)
sys.modules["compose_stability_report"] = _csr
_spec.loader.exec_module(_csr)
Comp = _csr.Comp
find_reports = _csr.find_reports
load_all = _csr.load_all

FUN_DECL = re.compile(r"\bfun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PARAM_NAME = re.compile(
    r"(?<![A-Za-z0-9_])(?:val\s+|var\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:"
)


def _log(msg: str) -> None:
    sys.stderr.write(f"[compose-stability] {msg}\n")
    sys.stderr.flush()


def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        parsed = urllib.parse.urlparse(uri)
        return urllib.parse.unquote(parsed.path)
    return uri


def find_root(path: str) -> str:
    curr = os.path.abspath(path if os.path.isdir(path) else os.path.dirname(path))
    while curr != "/":
        if os.path.exists(os.path.join(curr, "gradlew")) or os.path.exists(
            os.path.join(curr, "settings.gradle.kts")
        ):
            return curr
        curr = os.path.dirname(curr)
    return os.path.abspath(os.path.dirname(path))


def u16_len(s: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def pos(line: int, col: int) -> dict:
    return {"line": line, "character": col}


def rng(line: int, start: int, end: int) -> dict:
    return {"start": pos(line, start), "end": pos(line, end)}


class ReportIndex:
    def __init__(self) -> None:
        self.root = ""
        self.by_name: dict[str, list[Comp]] = {}
        self.stamp: tuple = ()

    def _stamp(self, root: str) -> tuple:
        paths = find_reports(root)
        return tuple((p, os.path.getmtime(p)) for p in paths)

    def ensure(self, root: str) -> None:
        if not root:
            return
        stamp = self._stamp(root)
        if stamp == self.stamp and root == self.root:
            return
        self.root = root
        self.stamp = stamp
        self.by_name = {}
        items = load_all(root)
        for c in items:
            self.by_name.setdefault(c.name, []).append(c)
            if c.simple != c.name:
                self.by_name.setdefault(c.simple, []).append(c)
        _log(f"loaded {len(items)} composables ({len(self.by_name)} name keys) from {root}")

    def pick(self, name: str, param_names: list[str]) -> Comp | None:
        cands = self.by_name.get(name) or []
        if not cands:
            return None
        if len(cands) == 1 or not param_names:
            return cands[0]
        best, score = cands[0], -1
        want = set(param_names)
        for c in cands:
            have = {p.text.split(":")[0].strip() for p in c.params}
            s = len(want & have)
            if s > score:
                best, score = c, s
        return best


REPORTS = ReportIndex()
DOCS: dict[str, str] = {}


def find_composables(text: str) -> list[dict]:
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = FUN_DECL.search(line)
        if not m:
            continue
        window = "\n".join(lines[max(0, i - 16) : i + 1])
        if "@Composable" not in window:
            continue
        name = m.group(1)
        start = u16_len(line[: m.start(1)])
        end = start + u16_len(name)
        sig, sig_end_line = extract_sig(lines, i, m.end() - 1)
        params = PARAM_NAME.findall(sig)
        out.append(
            {
                "name": name,
                "line": i,
                "start": start,
                "end": end,
                "preview": "@Preview" in window,
                "params": params,
                "sig": sig,
                "sig_end_line": sig_end_line,
            }
        )
    return out


def extract_sig(lines: list[str], start_line: int, start_col: int) -> tuple[str, int]:
    """Text from the '(' after fun Name through its matching ')'."""
    buf = []
    depth = 0
    started = False
    for li in range(start_line, min(len(lines), start_line + 80)):
        line = lines[li]
        col0 = start_col if li == start_line else 0
        for col, ch in enumerate(line[col0:], col0):
            if ch == "(":
                depth += 1
                started = True
            elif ch == ")":
                depth -= 1
                if started and depth <= 0:
                    buf.append(line[col0 : col + 1])
                    return "".join(buf), li
        buf.append(line[col0:] + "\n")
    return "".join(buf), start_line


def hover_md(c, name: str, has_reports: bool) -> str:
    if c is None:
        if not has_reports:
            return (
                f"**{name}** — no Compose compiler reports.\n\n"
                "Run task **Compose: Stability report** (or compile with "
                "`scripts/compose-reports.init.gradle`) then reopen this file."
            )
        return f"**{name}** — not in compiler reports (inline / other module / not compiled)."
    lines = [f"**{c.name}**", "", f"`{c.summary}`", ""]
    if c.params:
        lines.append("| param | stability |")
        lines.append("|---|---|")
        for p in c.params:
            pname, _, rest = p.text.partition(":")
            lines.append(f"| `{pname.strip()}` | **{p.stability}** `{rest.strip()}` |")
    else:
        lines.append("_no value parameters_")
    lines.append("")
    lines.append("_Static compiler inference — not live recomposition counts._")
    return "\n".join(lines)


def diagnostics_for(text: str) -> list[dict]:
    diags = []
    has = bool(REPORTS.by_name)
    for fn in find_composables(text):
        if fn["preview"]:
            continue
        c = REPORTS.pick(fn["name"], fn["params"])
        if not c or not c.issue:
            continue
        diags.append(
            {
                "range": rng(fn["line"], fn["start"], fn["end"]),
                "severity": 2,
                "source": "compose-stability",
                "message": c.summary,
            }
        )
    if not has and find_composables(text):
        # one info on first composable so the editor explains the empty state
        fn = find_composables(text)[0]
        diags.append(
            {
                "range": rng(fn["line"], fn["start"], fn["end"]),
                "severity": 3,
                "source": "compose-stability",
                "message": "No compose_compiler reports yet. Run Compose: Stability report.",
            }
        )
    return diags


def param_inlay_positions(text: str, fn: dict, c: Comp) -> list[dict]:
    lines = text.splitlines()
    hints = []
    by_pname = {}
    for p in c.params:
        by_pname[p.text.split(":")[0].strip()] = p.stability
    for li in range(fn["line"], fn["sig_end_line"] + 1):
        if li >= len(lines):
            break
        line = lines[li]
        for m in re.finditer(r"(?:^|[,(\s])([A-Za-z_][A-Za-z0-9_]*)\s*:", line):
            pname = m.group(1)
            stab = by_pname.get(pname)
            if not stab:
                continue
            col = u16_len(line[: m.end()])
            hints.append(
                {
                    "position": pos(li, col),
                    "label": f" {stab}",
                    "kind": 2,
                    "paddingLeft": False,
                    "paddingRight": True,
                }
            )
    return hints


def inlays_for(text: str) -> list[dict]:
    hints = []
    for fn in find_composables(text):
        c = REPORTS.pick(fn["name"], fn["params"])
        if not c:
            continue
        hints.append(
            {
                "position": pos(fn["line"], fn["end"]),
                "label": " skippable" if c.skippable else " not skippable",
                "kind": 1,
                "paddingLeft": True,
                "paddingRight": False,
            }
        )
        hints.extend(param_inlay_positions(text, fn, c))
    return hints


def read_message() -> dict | None:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, val = line.decode("ascii", "replace").partition(":")
        headers[key.strip().lower()] = val.strip()
    n = int(headers.get("content-length", "0") or 0)
    if n <= 0:
        return None
    body = sys.stdin.buffer.read(n)
    return json.loads(body.decode("utf-8"))


def write_message(msg: dict) -> None:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def reply(req: dict, result) -> None:
    if "id" not in req:
        return
    write_message({"jsonrpc": "2.0", "id": req["id"], "result": result})


def notify(method: str, params) -> None:
    write_message({"jsonrpc": "2.0", "method": method, "params": params})


def publish_diags(uri: str) -> None:
    text = DOCS.get(uri, "")
    path = uri_to_path(uri)
    REPORTS.ensure(find_root(path))
    notify(
        "textDocument/publishDiagnostics",
        {"uri": uri, "diagnostics": diagnostics_for(text)},
    )


def word_at(text: str, line: int, ch: int) -> tuple[str, int, int]:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return "", 0, 0
    s = lines[line]
    # ch is utf-16; map roughly via characters for kotlin
    i = min(ch, len(s))
    a = i
    while a > 0 and (s[a - 1].isalnum() or s[a - 1] == "_"):
        a -= 1
    b = i
    while b < len(s) and (s[b].isalnum() or s[b] == "_"):
        b += 1
    return s[a:b], a, b


def handle(msg: dict) -> bool:
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        root = ""
        if params.get("rootUri"):
            root = find_root(uri_to_path(params["rootUri"]))
        elif params.get("rootPath"):
            root = find_root(params["rootPath"])
        if root:
            REPORTS.ensure(root)
        reply(
            msg,
            {
                "capabilities": {
                    "textDocumentSync": 1,
                    "hoverProvider": True,
                    "inlayHintProvider": True,
                    "diagnosticProvider": {
                        "interFileDependencies": False,
                        "workspaceDiagnostics": False,
                    },
                },
                "serverInfo": {"name": "compose-stability", "version": "0.1.0"},
            },
        )
        return True

    if method == "initialized":
        return True

    if method == "shutdown":
        reply(msg, None)
        return True

    if method == "exit":
        return False

    if method == "textDocument/didOpen":
        doc = params["textDocument"]
        DOCS[doc["uri"]] = doc.get("text") or ""
        publish_diags(doc["uri"])
        return True

    if method == "textDocument/didChange":
        uri = params["textDocument"]["uri"]
        changes = params.get("contentChanges") or []
        if changes and "range" not in changes[-1]:
            DOCS[uri] = changes[-1].get("text") or ""
        publish_diags(uri)
        return True

    if method == "textDocument/didSave":
        uri = params["textDocument"]["uri"]
        publish_diags(uri)
        return True

    if method == "textDocument/didClose":
        DOCS.pop(params["textDocument"]["uri"], None)
        return True

    if method == "textDocument/hover":
        uri = params["textDocument"]["uri"]
        text = DOCS.get(uri, "")
        REPORTS.ensure(find_root(uri_to_path(uri)))
        p = params["position"]
        word, a, b = word_at(text, p.get("line", 0), p.get("character", 0))
        fns = [f for f in find_composables(text) if f["name"] == word]
        if not word or (word not in REPORTS.by_name and not fns):
            reply(msg, None)
            return True
        params_names = fns[0]["params"] if fns else []
        c = REPORTS.pick(word, params_names)
        reply(
            msg,
            {
                "contents": {"kind": "markdown", "value": hover_md(c, word, bool(REPORTS.by_name))},
                "range": rng(p.get("line", 0), a, b),
            },
        )
        return True

    if method == "textDocument/inlayHint":
        uri = params["textDocument"]["uri"]
        text = DOCS.get(uri, "")
        REPORTS.ensure(find_root(uri_to_path(uri)))
        reply(msg, inlays_for(text))
        return True

    if method == "textDocument/diagnostic":
        uri = params["textDocument"]["uri"]
        text = DOCS.get(uri, "")
        REPORTS.ensure(find_root(uri_to_path(uri)))
        reply(
            msg,
            {"kind": "full", "items": diagnostics_for(text)},
        )
        return True

    if "id" in msg:
        reply(msg, None)
    return True


def main() -> int:
    _log("stdio LSP starting")
    while True:
        try:
            msg = read_message()
        except Exception as e:
            _log(f"read error: {e}")
            return 1
        if msg is None:
            return 0
        try:
            if not handle(msg):
                return 0
        except Exception as e:
            _log(f"handle {msg.get('method')}: {e}")
            if "id" in msg:
                write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "error": {"code": -32603, "message": str(e)},
                    }
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
