#!/usr/bin/env python3
"""
Layout Inspector + live recomposition counts (copy of interactive_inspector.py).

Same tree / lazy expand as the original. Sidecar JDWP tracer (no app source).
Counts show only on currently visible (expanded) rows.

[e] one level  [E] max depth  [c] collapse  [r] refresh dump
[R] reset counts  [Enter] Zed  [q] quit (stops tracer)
"""

import curses
import importlib.util
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from functools import lru_cache

EXCLUDED_TYPES = {
    "Modifier", "String", "Color", "Int", "Alignment", "Arrangement", "Unit",
    "Pair", "List", "Set", "Map", "Boolean", "Float", "Double", "Long", "Dp",
    "OptIn", "Preview", "Composable", "DerivedStateOf", "Remember", "SideEffect",
    "LaunchedEffect", "DisposableEffect", "IntOffset", "Offset", "Size", "Brush",
    "MutableInteractionSource", "ColorMatrix", "ColorFilter", "Paint", "Path",
    "Random", "Matrix", "ContentScale", "LinearEasing",
    "RepeatMode", "InfiniteTransition", "Activity", "Context", "Intent", "Uri",
    "Settings", "ComponentName", "Lifecycle", "LifecycleOwner",
    "MaterialTheme", "LocalContext", "LocalLifecycleOwner", "WindowInsets",
    "GridCells", "ExperimentalLayoutApi", "Build", "Uri", "Intent",
    "ActivityResultContracts", "ContentScale",
    "StartActivityForResult", "LifecycleResumeEffect",
}

# Call-like PascalCase that is not a layout node
EXCLUDED_CALLS = EXCLUDED_TYPES | {
    "Intent", "Uri", "ComponentName", "Settings",
}

COMPOSE_CALL = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*[\(\{]")
FUN_DECL = re.compile(
    r"^\s*(?:(?:private|internal|public|protected|override|actual|expect)\s+)*"
    r"fun\s+([A-Za-z0-9_]+)\s*\("
)
SAMPLE_ARG = re.compile(
    r'(?:text|title|label|placeholder|contentDescription)\s*=\s*"([^"]+)"'
)

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_recomp():
    path = os.path.join(_HERE, "compose-recomposition.py")
    spec = importlib.util.spec_from_file_location("compose_recomposition", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _simple_name(fq: str) -> str:
    return (fq or "").rsplit(".", 1)[-1]


# Foundation/material names share one compiler key for the whole process.
# Showing that total on every Spacer/Text/Row makes ×1 jump to ×150+.
_SKIP_COUNT_NAMES = {
    "Spacer", "Row", "Column", "Box", "BoxWithConstraints", "Text", "Icon",
    "Image", "Padding", "Divider", "Surface", "Canvas", "Layout", "SubcomposeLayout",
    "LazyColumn", "LazyRow", "LazyVerticalGrid", "AndroidView", "Popup",
    "CompositionLocalProvider", "ProvideContentColor",
}


def _is_app_composable(fq: str, app_prefix: str) -> bool:
    if ".<anonymous>" in fq or "<get-" in fq:
        return False
    if fq.startswith(("androidx.", "android.", "kotlin.", "java.", "kotlinx.")):
        return False
    if app_prefix and "." in fq and not fq.startswith(app_prefix):
        return False
    return True


def index_recomp_rows(rows, app_prefix=""):
    """Project composables only. One bucket per function name (not per instance)."""
    by_name = {}
    by_file = {}
    for fq, where, n in rows:
        if not _is_app_composable(fq, app_prefix):
            continue
        short = _simple_name(fq)
        if not short or short[0].islower() or short in _SKIP_COUNT_NAMES:
            continue
        by_name[short] = by_name.get(short, 0) + n
        if short.endswith("Internal"):
            by_name[short[: -len("Internal")]] = (
                by_name.get(short[: -len("Internal")], 0) + n
            )
        if where:
            base = where.split(":")[0]
            by_file[(short, base)] = by_file.get((short, base), 0) + n
    return by_name, by_file


def _own_recomp_count(name, by_name):
    if not name:
        return None
    short = _simple_name(name)
    if not short or short in _SKIP_COUNT_NAMES:
        return None
    return by_name.get(short)


def recomp_count_for(node, by_name, by_file):
    """App composable's own tracer total, else nearest ancestor's.

    Foundation calls (Text/Row/Spacer) share one process-wide compiler key —
    never show that. They recompose with the enclosing @Composable, so
    inherit that parent's count.
    """
    own = _own_recomp_count(getattr(node, "composable_name", None), by_name)
    if own is not None:
        return own
    parent = getattr(node, "parent", None)
    while parent is not None:
        inherited = _own_recomp_count(getattr(parent, "composable_name", None), by_name)
        if inherited is not None:
            return inherited
        parent = getattr(parent, "parent", None)
    return None


def find_project_root():
    curr = os.path.abspath(os.getcwd())
    while curr != "/":
        if os.path.exists(os.path.join(curr, "settings.gradle.kts")) or \
           os.path.exists(os.path.join(curr, "settings.gradle")) or \
           os.path.exists(os.path.join(curr, "gradlew")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.abspath(os.getcwd())

PROJECT_ROOT = find_project_root()

@lru_cache(maxsize=1)
def kotlin_source_files():
    files = []
    skip = {"build", ".gradle", ".git", ".idea", ".zed"}
    for root, dirs, names in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in names:
            if name.endswith(".kt"):
                files.append(os.path.join(root, name))
    return files


def _has_composable_annotation(lines, fun_idx):
    start = max(0, fun_idx - 12)
    chunk = "".join(lines[start : fun_idx + 1])
    return "@Composable" in chunk


@lru_cache(maxsize=512)
def find_composable_definition(comp_name):
    """@Composable fun <comp_name>(… ) — project source only, skip Preview/Test."""
    if not comp_name or comp_name in EXCLUDED_CALLS:
        return None, None
    for path in kotlin_source_files():
        base = os.path.basename(path)
        if "Preview" in base or "Test" in base:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            m = FUN_DECL.match(line)
            if not m or m.group(1) != comp_name:
                continue
            if "Preview" in line:
                continue
            if not _has_composable_annotation(lines, idx):
                continue
            return path, idx + 1
    return None, None


def _mask_strings_and_comments(line, in_block_comment):
    """Replace string/comment contents so brace counts ignore them."""
    out = []
    i = 0
    n = len(line)
    in_string = False
    quote = ""
    while i < n:
        ch = line[i]
        nxt = line[i + 1] if i + 1 < n else ""
        if in_block_comment:
            out.append(" ")
            if ch == "*" and nxt == "/":
                out.append(" ")
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(" ")
            if ch == "\\" and nxt:
                out.append(" ")
                i += 2
                continue
            if ch == quote:
                in_string = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out.append(" " * (n - i))
            break
        if ch == "/" and nxt == "*":
            in_block_comment = True
            out.append("  ")
            i += 2
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block_comment


def find_body_open(lines, start_idx):
    """Index of the `{` that opens the function/call body after start_idx."""
    paren = 0
    in_block = False
    for idx in range(start_idx, len(lines)):
        masked, in_block = _mask_strings_and_comments(lines[idx], in_block)
        for ch in masked:
            if ch == "(":
                paren += 1
            elif ch == ")":
                paren = max(0, paren - 1)
            elif ch == "{" and paren == 0:
                return idx
    return None

class ASTNode:
    def __init__(self, name, line_no, file_path, sample_text=''):
        self.name = name
        self.line_no = line_no
        self.file_path = file_path
        self.sample_text = sample_text
        self.children = []

@lru_cache(maxsize=256)
def parse_composable_block_at_line(file_path, target_line):
    """Parse the full `{ ... }` body starting at target_line. No line cap."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    start_idx = max(0, int(target_line) - 1)
    body_start_idx = find_body_open(lines, start_idx)
    if body_start_idx is None:
        return []

    root_nodes = []
    stack = []  # (node, brace_depth of that node's content lambda)
    current_brace = 0
    in_block = False
    # Trailing-lambda only: Name(...) {  — not if/else/remember braces.
    await_lambda = None  # ASTNode waiting for optional { after its ( ... )
    call_parens = 0

    def attach(node):
        if stack:
            stack[-1][0].children.append(node)
        else:
            root_nodes.append(node)

    for idx in range(body_start_idx, len(lines)):
        raw = lines[idx]
        line_no = idx + 1
        masked, in_block = _mask_strings_and_comments(raw, in_block)
        stripped = raw.strip()
        skip_scan = (
            idx == body_start_idx
            or not stripped
            or stripped.startswith("//")
            or stripped.startswith("*")
            or stripped.startswith("/*")
        )

        # Map masked index → composable start so we walk one stream.
        call_at = {}
        if not skip_scan:
            for m in COMPOSE_CALL.finditer(raw):
                cname = m.group(1)
                if cname in EXCLUDED_CALLS or "Preview" in cname:
                    continue
                sample = ""
                arg = SAMPLE_ARG.search(raw)
                if arg:
                    sample = arg.group(1)
                else:
                    sm = re.search(r'"([^"]{1,40})"', raw)
                    if sm and not sm.group(1).startswith("android."):
                        sample = sm.group(1)
                call_at[m.start()] = ASTNode(cname, str(line_no), file_path, sample)

        i = 0
        while i < len(masked):
            if i in call_at:
                node = call_at[i]
                attach(node)
                # skip the identifier; next char in masked is ( or {
                j = i
                while j < len(masked) and (masked[j].isalnum() or masked[j] == "_"):
                    j += 1
                while j < len(masked) and masked[j] in " \t":
                    j += 1
                if j < len(masked) and masked[j] == "(":
                    await_lambda = node
                    call_parens = 1
                    i = j + 1
                    continue
                if j < len(masked) and masked[j] == "{":
                    stack.append((node, current_brace))
                    current_brace += 1
                    await_lambda = None
                    call_parens = 0
                    i = j + 1
                    continue
                i = j
                continue

            ch = masked[i]
            if await_lambda is not None and call_parens > 0:
                if ch == "(":
                    call_parens += 1
                elif ch == ")":
                    call_parens -= 1
                i += 1
                continue

            if await_lambda is not None and call_parens == 0:
                if ch in " \t\n\r":
                    i += 1
                    continue
                if ch == "{":
                    stack.append((await_lambda, current_brace))
                    current_brace += 1
                    await_lambda = None
                    i += 1
                    continue
                # Not a trailing lambda (next statement / if / else).
                await_lambda = None

            if ch == "{":
                current_brace += 1
            elif ch == "}":
                current_brace -= 1
                while stack and current_brace <= stack[-1][1]:
                    stack.pop()
                if current_brace <= 0:
                    return root_nodes
            i += 1

    return root_nodes

@lru_cache(maxsize=128)
def parse_kotlin_composable_chain(file_path, target_line):
    """Extracts Composable call stack at target line."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return [], None

    target_idx = min(len(lines), max(1, target_line)) - 1
    stack = []
    enclosing_function = None

    for idx in range(target_idx + 1):
        line = lines[idx].strip()
        line_num = idx + 1

        if line.startswith("@Composable"):
            for f_idx in range(idx, min(len(lines), idx + 3)):
                m_fun = re.search(r"fun\s+([A-Za-z0-9_]+)", lines[f_idx])
                if m_fun:
                    enclosing_function = m_fun.group(1)
                    stack = [(enclosing_function, f_idx + 1)]
                    break

        comp_matches = re.finditer(r"\b([A-Z][A-Za-z0-9_]+)\s*[\(\{]", line)
        for m in comp_matches:
            c_name = m.group(1)
            if c_name not in EXCLUDED_TYPES:
                stack.append((c_name, line_num))

    return stack, enclosing_function

def _is_composable_source_hit(file_path, line_no, line_content):
    """Only hits inside a real @Composable fun — skip catalogs / data classes."""
    if not file_path.endswith(".kt"):
        return False
    base = os.path.basename(file_path)
    if "Preview" in base or "Test" in base:
        return False
    stripped = line_content.strip()
    if re.search(r"\b(data class|object |enum class)\b", stripped):
        return False
    _, enclosing = parse_kotlin_composable_chain(file_path, line_no)
    if not enclosing:
        return False
    return bool(find_composable_definition(enclosing)[0])


def _primary_layout_composable(chain):
    """Last name in the chain that is actually @Composable fun in this project."""
    for name, _ in reversed(chain):
        if name in EXCLUDED_CALLS:
            continue
        path, _line = find_composable_definition(name)
        if path:
            return name
    return None


@lru_cache(maxsize=512)
def resolve_composable_from_source(search_term):
    """Map visible text to a @Composable call site — never a data-class constructor."""
    if not search_term or len(search_term) < 2:
        return None

    cmd = [
        "grep", "-rnI",
        "--include=*.kt",
        "--exclude-dir=build", "--exclude-dir=.gradle", "--exclude-dir=.git", "--exclude-dir=.idea",
        search_term, PROJECT_ROOT
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        hits = [l for l in res.stdout.splitlines() if l]
        parsed = []
        for raw in hits:
            match = re.match(r"^([^:]+):(\d+):(.*)$", raw)
            if not match:
                continue
            file_path, line_no_str, line_content = match.group(1), match.group(2), match.group(3)
            line_no = int(line_no_str)
            if not _is_composable_source_hit(file_path, line_no, line_content):
                continue
            chain, enclosing_func = parse_kotlin_composable_chain(file_path, line_no)
            primary = _primary_layout_composable(chain) or enclosing_func
            parsed.append(
                {
                    "file_path": file_path,
                    "line_no": str(line_no),
                    "composable": primary,
                    "enclosing": enclosing_func,
                    "hierarchy_chain": [c[0] for c in chain],
                    "line_content": line_content.strip(),
                }
            )
        if not parsed:
            return None
        # Prefer a hit whose name has a project @Composable definition.
        for item in parsed:
            if item["composable"] and find_composable_definition(item["composable"])[0]:
                return item
        return parsed[0]
    except Exception:
        return None

class UINode:
    def __init__(self, elem=None, parent=None, depth=0, ast_node=None):
        self.parent = parent
        self.depth = depth
        self.children = []
        self.expanded = False
        self._source_resolved = False
        self._def_loaded = False

        if ast_node:
            self.attrib = {}
            self.raw_class = ""
            self.class_name = ast_node.name
            self.res_id = ""
            self.text = ast_node.sample_text
            self.content_desc = ""
            self.bounds = ""
            self.clickable = False
            self.is_synthetic = True
            
            self.source_file = ast_node.file_path
            self.source_line = ast_node.line_no
            self.composable_name = ast_node.name
            self.enclosing_screen = None
            self.hierarchy_chain = [self.composable_name]
            self._source_resolved = True

            for child_ast in ast_node.children:
                self.children.append(UINode(parent=self, depth=depth + 1, ast_node=child_ast))
        else:
            self.attrib = elem.attrib if elem is not None else {}
            self.raw_class = self.attrib.get("class", "")
            self.class_name = self.raw_class.split(".")[-1]
            
            raw_id = self.attrib.get("resource-id", "")
            self.res_id = raw_id.split("/")[-1] if "/" in raw_id else raw_id
            
            self.text = self.attrib.get("text", "").strip()
            self.content_desc = self.attrib.get("content-desc", "").strip()
            self.bounds = self.attrib.get("bounds", "")
            self.clickable = self.attrib.get("clickable", "false") == "true"
            self.is_synthetic = False
            
            self.source_file = None
            self.source_line = None
            self.composable_name = None
            self.enclosing_screen = None
            self.hierarchy_chain = []

            if elem is not None:
                for child_elem in elem:
                    self.children.append(UINode(child_elem, self, depth + 1))

    def ensure_source_resolved(self):
        """Universal source resolution for ANY node."""
        if self._source_resolved:
            return
        self._source_resolved = True

        candidates = []
        if self.res_id:
            candidates.extend([f'"{self.res_id}"', f'testTag = "{self.res_id}"', f'testTag("{self.res_id}")', f'R.id.{self.res_id}'])
        if self.text and len(self.text) >= 2:
            candidates.append(f'"{self.text}"')
            if not self.text.startswith('"'):
                candidates.append(f'text = "{self.text}"')
                candidates.append(f'title = "{self.text}"')
        if self.content_desc and len(self.content_desc) >= 3:
            candidates.append(f'"{self.content_desc}"')

        for candidate in candidates:
            info = resolve_composable_from_source(candidate)
            if info:
                self.source_file = info["file_path"]
                self.source_line = info["line_no"]
                self.composable_name = info["composable"]
                self.enclosing_screen = info["enclosing"]
                self.hierarchy_chain = info.get("hierarchy_chain", [])
                break

    def _adopt_ast_roots(self, ast_roots):
        existing = {(c.composable_name, str(c.source_line)) for c in self.children}
        added = False
        for ast_root in ast_roots:
            if ast_root.name == self.composable_name:
                continue
            key = (ast_root.name, str(ast_root.line_no))
            if key in existing:
                continue
            self.children.append(UINode(parent=self, depth=self.depth + 1, ast_node=ast_root))
            existing.add(key)
            added = True
        if added:
            self.recalculate_depths(self.depth)
        return added

    def _infer_composable_name(self):
        if self.composable_name and find_composable_definition(self.composable_name)[0]:
            return self.composable_name
        return self.composable_name

    def can_deepen(self):
        """True only if expand will reveal nodes we don't already show."""
        if self.children and not self.expanded:
            return True
        self.ensure_source_resolved()
        name = self._infer_composable_name()
        if name and find_composable_definition(name)[0]:
            # already showing that definition's kids?
            if self._def_loaded and not self.children:
                return False
            if self._def_loaded and self.expanded:
                return bool(self.children)
            return True
        return False

    def ensure_ast_children_expanded(self):
        """Load this node's next hierarchy level from its @Composable definition."""
        self.ensure_source_resolved()
        if self._def_loaded:
            return
        self._def_loaded = True

        name = self._infer_composable_name()
        if name and name != self.composable_name:
            self.composable_name = name

        ast_roots = []
        def_file = def_line = None
        if name:
            def_file, def_line = find_composable_definition(name)
            if def_file and def_line:
                ast_roots = parse_composable_block_at_line(def_file, def_line)

        # Already a UINode built from this same function body — don't re-parse.
        same_file_def = (
            def_file
            and self.source_file
            and os.path.abspath(self.source_file) == os.path.abspath(def_file)
            and self.is_synthetic
            and self.children
        )
        if same_file_def:
            return

        if ast_roots:
            self._adopt_ast_roots(ast_roots)

    def recalculate_depths(self, start_depth=0):
        self.depth = start_depth
        for child in self.children:
            child.recalculate_depths(start_depth + 1)

    def get_layout_tag(self):
        self.ensure_source_resolved()
        if self.composable_name:
            prefix = "" if not self.is_synthetic else "› "
            return f"{prefix}<{self.composable_name}>"
        
        if self.raw_class and not self.raw_class.startswith("android.view."):
            return self.class_name
        
        if self.clickable:
            return "<Clickable>"
        if self.text:
            return "<Text>"
        if self.content_desc:
            return "<Icon/Image>"
        if self.children:
            return "<Container>"
        
        return self.class_name if self.class_name else "<View>"

    def display_text(self):
        parts = [self.get_layout_tag()]
        
        if self.res_id:
            parts.append(f"#{self.res_id}")
        if self.text:
            escaped = self.text.replace("\n", "\\n")
            if len(escaped) > 30:
                escaped = escaped[:27] + "..."
            parts.append(f'"{escaped}"')
        if self.content_desc:
            desc = self.content_desc.replace("\n", "\\n")
            if len(desc) > 25:
                desc = desc[:22] + "..."
            parts.append(f'[desc: {desc}]')
        if self.clickable:
            parts.append("(clickable)")
        if self.bounds:
            parts.append(self.bounds)
            
        return " ".join(parts)

    def full_info(self):
        self.ensure_source_resolved()
        info = [f"Depth: L{self.depth}"]
        if self.composable_name:
            info.append(f"Component: <{self.composable_name}>")
        if self.hierarchy_chain:
            chain_str = " > ".join(self.hierarchy_chain[-4:])
            info.append(f"Hierarchy: {chain_str}")
        elif self.enclosing_screen:
            info.append(f"In: {self.enclosing_screen}()")
            
        if self.source_file and self.source_line:
            rel_file = os.path.relpath(self.source_file, PROJECT_ROOT)
            info.append(f"Source: {rel_file}:{self.source_line}")
        elif self.raw_class:
            info.append(f"Class: {self.raw_class}")
            
        if self.bounds:
            info.append(f"Bounds: {self.bounds}")
            
        return " | ".join(info)

def find_compose_root(node):
    if not node:
        return None
    if "ComposeView" in node.class_name or "compose" in node.res_id.lower():
        return node
    for child in node.children:
        found = find_compose_root(child)
        if found:
            return found
    return node

def set_expand_depth(node, current_depth, max_depth, ancestors=None):
    if not node:
        return
    ancestors = list(ancestors or [])
    node.ensure_ast_children_expanded()
    node.expanded = current_depth < max_depth and bool(node.children)
    if not node.expanded:
        return
    name = node.composable_name
    nxt = ancestors + [name] if name else ancestors
    for child in node.children:
        if child.composable_name and child.composable_name in ancestors:
            continue
        set_expand_depth(child, current_depth + 1, max_depth, nxt)


def expand_to_max_depth(node, ancestors=None, hops=0):
    """Lazily load and expand every descendant until definitions run out."""
    if not node or hops > 48:
        return 0
    ancestors = list(ancestors or [])
    node.ensure_ast_children_expanded()
    if not node.children:
        node.expanded = False
        return 0
    node.expanded = True
    name = node.composable_name
    nxt = ancestors + [name] if name else ancestors
    opened = 1
    for child in node.children:
        if child.composable_name and child.composable_name in ancestors:
            continue
        opened += expand_to_max_depth(child, nxt, hops + 1)
    return opened


def toggle_node_stepwise(node):
    """Expand one level, or collapse if already open."""
    if not node:
        return "No node selected."

    node.ensure_ast_children_expanded()
    label = node.get_layout_tag().strip("<>")

    if not node.children:
        return f"<{label}> is a leaf (no deeper layout)."

    if not node.expanded:
        node.expanded = True
        return f"Expanded <{label}> ({len(node.children)} children)"
    node.expanded = False
    return f"Collapsed <{label}>"

def fetch_ui_dump():
    cmd_env = os.environ.copy()
    adb_target = []
    if "ANDROID_SERIAL" in cmd_env:
        adb_target = ["-s", cmd_env["ANDROID_SERIAL"]]

    dump_cmd = ["adb"] + adb_target + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]
    res = subprocess.run(dump_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"uiautomator dump failed: {res.stderr.strip() or res.stdout.strip()}")

    dump_path = "/tmp/zed-android-window_dump.xml"
    pull_cmd = ["adb"] + adb_target + ["pull", "/sdcard/window_dump.xml", dump_path]
    res = subprocess.run(pull_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"adb pull failed: {res.stderr.strip()}")

    return dump_path

def jump_to_ide(file_path, line_num):
    target = f"{file_path}:{line_num}"
    if subprocess.run(["which", "zed"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.Popen(["zed", target])
        return f"Opened {os.path.basename(file_path)}:{line_num} in Zed"
    
    if subprocess.run(["which", "code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.Popen(["code", "-g", target])
        return f"Opened {os.path.basename(file_path)}:{line_num} in VS Code"
    
    subprocess.Popen(["open", file_path])
    return f"Opened {os.path.basename(file_path)}"

def flatten_tree(node, filter_query=""):
    if not node:
        return []
    
    items = []
    text_repr = node.display_text().lower()
    matches_filter = (not filter_query) or (filter_query.lower() in text_repr)
    
    if matches_filter or filter_query:
        items.append(node)
        
    if node.expanded:
        for child in node.children:
            items.extend(flatten_tree(child, filter_query if not matches_filter else ""))
    return items

def run_tui(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.timeout(200)
    stdscr.keypad(True)
    
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)    # Selected row
    curses.init_pair(2, curses.COLOR_YELLOW, -1)                   # Depth/markers
    curses.init_pair(3, curses.COLOR_GREEN, -1)                    # Composable highlight
    curses.init_pair(4, curses.COLOR_RED, -1)                      # Error info
    curses.init_pair(5, curses.COLOR_CYAN, -1)                     # Details header
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)                  # Synthetic AST child highlight
    curses.init_pair(7, curses.COLOR_GREEN, -1)                    # recomp count

    status_msg = "Capturing UI hierarchy..."
    raw_root = None
    active_root = None
    focus_compose_only = True
    filter_query = ""
    recomp = RECOMP.get("mod")
    recomp_pkg = RECOMP.get("pkg")
    recomp_ok = bool(RECOMP.get("ok"))
    recomp_err = RECOMP.get("err") or ""
    by_name, by_file = {}, {}
    last_snap = 0.0
    last_paint_sig = None
    app_prefix = (recomp_pkg or "").strip()

    def refresh_screen():
        nonlocal raw_root, active_root, status_msg
        try:
            resolve_composable_from_source.cache_clear()
            parse_kotlin_composable_chain.cache_clear()
            find_composable_definition.cache_clear()
            parse_composable_block_at_line.cache_clear()
            kotlin_source_files.cache_clear()
            
            path = fetch_ui_dump()
            tree = ET.parse(path)
            xml_root = tree.getroot()
            
            dummy = ET.Element("Screen")
            dummy.attrib["class"] = "RootWindow"
            for c in xml_root:
                dummy.append(c)
            
            raw_root = UINode(dummy, depth=0)
            
            update_active_view()
            set_expand_depth(active_root, 0, 1)
            extra = "  counts on" if recomp_ok else f"  {recomp_err}" if recomp_err else ""
            status_msg = (
                "Ready. [e]+1  [E]max  [c]collapse  [R]reset counts  [Enter]Zed"
                + extra
            )
        except Exception as e:
            status_msg = f"ADB Error: {e}"

    def update_active_view():
        nonlocal active_root
        if not raw_root:
            return
        if focus_compose_only:
            comp_root = find_compose_root(raw_root)
            active_root = comp_root if comp_root else raw_root
        else:
            active_root = raw_root
            
        active_root.recalculate_depths(0)

    refresh_screen()
    cursor_idx = 0
    scroll_offset = 0

    while True:
        h, w = stdscr.getmaxyx()
        status_y = max(0, h - 1)
        
        now = time.time()
        if recomp_ok and recomp and recomp_pkg and (now - last_snap) >= 0.4:
            try:
                rows = recomp.pull_snapshot(recomp_pkg)
                if rows is not None:
                    by_name, by_file = index_recomp_rows(rows, app_prefix)
            except Exception:
                pass
            last_snap = now

        visible_items = flatten_tree(active_root, filter_query) if active_root else []
        total_items = len(visible_items)
        if total_items > 0:
            cursor_idx = max(0, min(cursor_idx, total_items - 1))
        else:
            cursor_idx = 0

        view_height = max(1, h - 4)
        if cursor_idx < scroll_offset:
            scroll_offset = cursor_idx
        elif cursor_idx >= scroll_offset + view_height:
            scroll_offset = cursor_idx - view_height + 1

        count_sig = tuple(
            recomp_count_for(n, by_name, by_file) for n in visible_items
        )
        paint_sig = (
            h,
            w,
            cursor_idx,
            scroll_offset,
            status_msg,
            focus_compose_only,
            count_sig,
            tuple((id(n), n.expanded) for n in visible_items),
        )
        if paint_sig == last_paint_sig:
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                break
            if key == -1:
                continue
        else:
            last_paint_sig = paint_sig
            stdscr.erase()
            mode_tag = "[Compose Root]" if focus_compose_only else "[All Window]"
            cnt_tag = "[recomp ON]" if recomp_ok else "[recomp off]"
            header = (
                f" [Inspector+recomp] {mode_tag} {cnt_tag}  "
                f"[e]+1 [E]max [c]collapse [r]dump [R]reset [q] "
            )
            stdscr.addstr(0, 0, header[:w-1].ljust(w-1), curses.A_REVERSE | curses.A_BOLD)

            for row in range(view_height):
                item_idx = scroll_offset + row
                if item_idx >= total_items:
                    break
                
                node = visible_items[item_idx]
                depth_tag = f"L{node.depth:02d} "
                indent = " " * (node.depth * 2)
                has_expandable_children = node.can_deepen() or (node.expanded and node.children)
                prefix = ("▼ " if node.expanded else "▶ ") if has_expandable_children else "• "
                
                count = recomp_count_for(node, by_name, by_file)
                count_bit = f"  ×{count}" if count is not None else ""
                line_str = f"{depth_tag}{indent}{prefix}{node.display_text()}{count_bit}"
                is_selected = (item_idx == cursor_idx)
                
                y = row + 1
                if is_selected:
                    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                    stdscr.addstr(y, 0, line_str[:w-1].ljust(w-1))
                    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                else:
                    if node.is_synthetic:
                        stdscr.addstr(y, 0, line_str[:w-1], curses.color_pair(6))
                    elif node.composable_name:
                        stdscr.addstr(y, 0, line_str[:w-1], curses.color_pair(3) | curses.A_BOLD)
                    else:
                        stdscr.addstr(y, 0, line_str[:w-1])

            detail_y = h - 3
            if visible_items and cursor_idx < len(visible_items):
                cur_node = visible_items[cursor_idx]
                detail_str = f" {cur_node.full_info()}"
                stdscr.addstr(detail_y, 0, detail_str[:w-1].ljust(w-1), curses.color_pair(5) | curses.A_BOLD)

            status_y = h - 1
            msg_color = curses.color_pair(3) if ("Opened" in status_msg or "Ready" in status_msg or "Expanded" in status_msg or "reset" in status_msg) else curses.color_pair(4)
            stdscr.addstr(status_y, 0, f" Status: {status_msg}"[:w-1].ljust(w-1), msg_color | curses.A_BOLD)
            stdscr.refresh()

            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                break
            if key == -1:
                continue
        if key in (ord('q'), 17, 27):  # 'q', Ctrl+Q, ESC (Q is unused; R resets)
            break
        elif key in (curses.KEY_UP, ord('k')):
            cursor_idx = max(0, cursor_idx - 1)
        elif key in (curses.KEY_DOWN, ord('j')):
            cursor_idx = min(total_items - 1, cursor_idx + 1)
        elif key == curses.KEY_NPAGE:
            cursor_idx = min(total_items - 1, cursor_idx + 10)
        elif key == curses.KEY_PPAGE:
            cursor_idx = max(0, cursor_idx - 10)
        elif key in (curses.KEY_LEFT, ord('h')):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                if node.expanded and node.children:
                    node.expanded = False
                elif node.parent and node.parent.expanded:
                    for idx, v_node in enumerate(visible_items):
                        if v_node == node.parent:
                            cursor_idx = idx
                            break
        elif key in (curses.KEY_RIGHT, ord('l'), ord(' ')):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                node.ensure_ast_children_expanded()
                if not node.expanded and node.children:
                    node.expanded = True
                elif node.expanded and node.children:
                    node.expanded = False
        elif key == ord('e'):
            if visible_items and cursor_idx < len(visible_items):
                status_msg = toggle_node_stepwise(visible_items[cursor_idx])
        elif key == ord('E'):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                n = expand_to_max_depth(node)
                label = node.get_layout_tag().strip("<>")
                status_msg = f"Expanded <{label}> to max depth ({n} nodes opened)"
        elif key in (ord('c'), ord('C')):  # 'c' collapses all
            set_expand_depth(active_root, 0, 1)
            cursor_idx = 0
            scroll_offset = 0
            status_msg = "Collapsed all nodes back to root."
        elif key == ord('f'):
            focus_compose_only = not focus_compose_only
            update_active_view()
            set_expand_depth(active_root, 0, 1)
            status_msg = "Focused Compose application root." if focus_compose_only else "Showing full window hierarchy."
        elif ord('1') <= key <= ord('9'):
            target_depth = key - ord('0')
            set_expand_depth(active_root, 0, target_depth)
            status_msg = f"Expanded tree to Depth L{target_depth}."
        elif key == ord('r'):
            status_msg = "Refreshing screen dump..."
            stdscr.addstr(status_y, 0, f" Status: {status_msg}"[:w-1].ljust(w-1), curses.A_BOLD)
            stdscr.refresh()
            refresh_screen()
        elif key == ord('R'):
            if recomp_ok and recomp and recomp_pkg:
                recomp.write_cmd(recomp_pkg, "reset")
                by_name, by_file = {}, {}
                status_msg = "Recomposition counts reset."
            else:
                status_msg = recomp_err or "tracer not attached"
        elif key in (curses.KEY_ENTER, 10, 13, ord('o')):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                node.ensure_source_resolved()
                if node.source_file and node.source_line:
                    status_msg = jump_to_ide(node.source_file, node.source_line)
                else:
                    status_msg = f"No source file found for {node.display_text()}"

RECOMP = {"mod": None, "pkg": None, "ok": False, "err": ""}


def main():
    print("injecting recomposition tracer (debug process)…", flush=True)
    try:
        RECOMP["mod"] = _load_recomp()
        RECOMP["pkg"] = RECOMP["mod"].resolve_pkg()
        pid = RECOMP["mod"].app_pid(RECOMP["pkg"])
        if not pid:
            RECOMP["err"] = f"{RECOMP['pkg']} not running — counts off"
            print(RECOMP["err"], flush=True)
        else:
            RECOMP["mod"].inject(RECOMP["pkg"], pid)
            RECOMP["ok"] = True
            print("tracer on — opening inspector", flush=True)
    except Exception as e:
        RECOMP["err"] = f"tracer: {e}"
        print(RECOMP["err"], flush=True)
    try:
        curses.wrapper(run_tui)
    except KeyboardInterrupt:
        pass
    finally:
        if RECOMP.get("mod") and RECOMP.get("pkg"):
            try:
                RECOMP["mod"].write_cmd(RECOMP["pkg"], "off")
            except Exception:
                pass
    sys.exit(0)

if __name__ == "__main__":
    main()
