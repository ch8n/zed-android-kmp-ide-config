#!/usr/bin/env python3
"""
Interactive Terminal Layout Inspector for Android / Jetpack Compose / KMP
Deeply resolves Composable component hierarchies, expands internal Composable definitions
down to maximum depth, and jumps directly to source code in Zed IDE.
"""

import curses
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache

EXCLUDED_TYPES = {
    "Modifier", "String", "Color", "Int", "Alignment", "Arrangement", "Unit", 
    "Pair", "List", "Set", "Map", "Boolean", "Float", "Double", "Long", "Dp",
    "OptIn", "Preview", "Composable", "DerivedStateOf", "Remember", "SideEffect",
    "LaunchedEffect", "DisposableEffect", "IntOffset", "Offset", "Size", "Brush"
}

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

@lru_cache(maxsize=128)
def find_composable_definition(comp_name):
    """Finds the source file and line where @Composable fun <comp_name> is defined."""
    if not comp_name or comp_name in EXCLUDED_TYPES:
        return None, None
    
    cmd = [
        "grep", "-rnI",
        "--include=*.kt",
        "--exclude-dir=build", "--exclude-dir=.gradle", "--exclude-dir=.git", "--exclude-dir=.idea",
        f"fun {comp_name}\\s*(", PROJECT_ROOT
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        for line in res.stdout.strip().split("\n"):
            if line and "Preview" not in line and "Test" not in line:
                m = re.match(r"^([^:]+):(\d+):", line)
                if m:
                    return m.group(1), int(m.group(2))
    except Exception:
        pass
    return None, None

@lru_cache(maxsize=128)
def parse_composable_body_subnodes(file_path, start_line):
    """Parses internal Composable function calls within a Composable body."""
    subnodes = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        
        start_idx = start_line - 1
        # Scan body up to 100 lines or until matching closing brace
        brace_count = 0
        body_started = False

        for idx in range(start_idx, min(len(lines), start_idx + 120)):
            line = lines[idx]
            line_no = idx + 1
            
            if "{" in line:
                brace_count += line.count("{")
                body_started = True
            if "}" in line:
                brace_count -= line.count("}")

            if body_started and brace_count <= 0 and idx > start_idx:
                break

            # Find composable invocations
            for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]+)\s*[\(\{]", line):
                name = m.group(1)
                if name not in EXCLUDED_TYPES:
                    # Extract sample text or argument if present
                    arg_match = re.search(r'(?:text|title|label|placeholder|contentDescription)\s*=\s*"([^"]+)"', line)
                    sample_text = arg_match.group(1) if arg_match else ""
                    if not sample_text:
                        str_match = re.search(r'"([^"]{2,30})"', line)
                        if str_match and not str_match.group(1).startswith("android."):
                            sample_text = str_match.group(1)
                            
                    subnodes.append({
                        "name": name,
                        "line_no": str(line_no),
                        "file_path": file_path,
                        "sample_text": sample_text
                    })
    except Exception:
        pass
    return subnodes

@lru_cache(maxsize=128)
def parse_kotlin_composable_chain(file_path, target_line):
    """Parses a Kotlin file and extracts the exact Composable parent hierarchy at target line."""
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

@lru_cache(maxsize=512)
def resolve_composable_from_source(search_term):
    """Searches for term in project source and extracts full Composable hierarchy."""
    if not search_term or len(search_term) < 2:
        return None

    cmd = [
        "grep", "-rnI",
        "--include=*.kt", "--include=*.java", "--include=*.xml",
        "--exclude-dir=build", "--exclude-dir=.gradle", "--exclude-dir=.git", "--exclude-dir=.idea",
        search_term, PROJECT_ROOT
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        lines = [l for l in res.stdout.strip().split("\n") if l]
        if not lines:
            return None
        
        chosen_line = lines[0]
        for l in lines:
            if "Preview" not in l and "Test" not in l:
                chosen_line = l
                break

        match = re.match(r"^([^:]+):(\d+):(.*)$", chosen_line)
        if not match:
            return None

        file_path, line_no_str, line_content = match.group(1), match.group(2), match.group(3)
        line_no = int(line_no_str)

        chain, enclosing_func = parse_kotlin_composable_chain(file_path, line_no)
        primary_comp = chain[-1][0] if chain else None
        
        return {
            "file_path": file_path,
            "line_no": str(line_no),
            "composable": primary_comp,
            "enclosing": enclosing_func,
            "hierarchy_chain": [c[0] for c in chain],
            "line_content": line_content.strip()
        }
    except Exception:
        return None

class UINode:
    def __init__(self, elem=None, parent=None, depth=0, synthetic_info=None):
        self.parent = parent
        self.depth = depth
        self.children = []
        self.expanded = True

        if synthetic_info:
            # Synthetic AST subnode from source code definition
            self.attrib = {}
            self.raw_class = ""
            self.class_name = synthetic_info.get("name", "Composable")
            self.res_id = ""
            self.text = synthetic_info.get("sample_text", "")
            self.content_desc = ""
            self.bounds = ""
            self.clickable = False
            self.is_synthetic = True
            
            self.source_file = synthetic_info.get("file_path")
            self.source_line = synthetic_info.get("line_no")
            self.composable_name = synthetic_info.get("name")
            self.enclosing_screen = None
            self.hierarchy_chain = [self.composable_name]
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
            
            self._resolve_direct_source()

            if elem is not None:
                for child_elem in elem:
                    self.children.append(UINode(child_elem, self, depth + 1))

    def _resolve_direct_source(self):
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

    def propagate_hierarchy(self):
        """Propagates Composable names and synthesizes AST sub-trees for leaf composables."""
        for child in self.children:
            child.propagate_hierarchy()

        # Inferred parent composable names from children
        if not self.composable_name and self.children:
            for child in self.children:
                if child.hierarchy_chain:
                    if len(child.hierarchy_chain) > 1:
                        self.composable_name = child.hierarchy_chain[-2]
                    elif child.enclosing_screen:
                        self.composable_name = child.enclosing_screen
                    
                    self.source_file = child.source_file
                    self.source_line = child.source_line
                    self.enclosing_screen = child.enclosing_screen
                    self.hierarchy_chain = child.hierarchy_chain[:-1]
                    break

        # If this is a named custom Composable and has NO accessibility children,
        # expand its internal Composable AST sub-nodes from Kotlin source!
        if self.composable_name and not self.children and not self.is_synthetic:
            self._expand_internal_ast_subtree()

    def _expand_internal_ast_subtree(self):
        """Expands the internal layout tree of a Composable function."""
        def_file, def_line = find_composable_definition(self.composable_name)
        if not def_file and self.source_file:
            def_file, def_line = self.source_file, int(self.source_line or 1)

        if def_file and def_line:
            subnodes = parse_composable_body_subnodes(def_file, def_line)
            # Add up to 8 key internal child composables
            for sub in subnodes[:8]:
                if sub["name"] != self.composable_name:
                    child_node = UINode(parent=self, depth=self.depth + 1, synthetic_info=sub)
                    self.children.append(child_node)

    def recalculate_depths(self, start_depth=0):
        self.depth = start_depth
        for child in self.children:
            child.recalculate_depths(start_depth + 1)

    def get_layout_tag(self):
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
    if "ComposeView" in node.class_name or "compose" in node.res_id.lower() or node.composable_name:
        return node
    for child in node.children:
        found = find_compose_root(child)
        if found:
            return found
    return node

def set_expand_depth(node, current_depth, max_depth):
    if not node:
        return
    node.expanded = (current_depth < max_depth)
    for child in node.children:
        set_expand_depth(child, current_depth + 1, max_depth)

def fetch_ui_dump():
    cmd_env = os.environ.copy()
    adb_target = []
    if "ANDROID_SERIAL" in cmd_env:
        adb_target = ["-s", cmd_env["ANDROID_SERIAL"]]

    dump_cmd = ["adb"] + adb_target + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]
    res = subprocess.run(dump_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"uiautomator dump failed: {res.stderr.strip() or res.stdout.strip()}")

    dump_path = "/tmp/piximon_window_dump.xml"
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
    
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)    # Selected row
    curses.init_pair(2, curses.COLOR_YELLOW, -1)                   # Depth/markers
    curses.init_pair(3, curses.COLOR_GREEN, -1)                    # Composable highlight
    curses.init_pair(4, curses.COLOR_RED, -1)                      # Error info
    curses.init_pair(5, curses.COLOR_CYAN, -1)                     # Details header
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)                  # Synthetic AST child highlight

    status_msg = "Capturing UI hierarchy..."
    raw_root = None
    active_root = None
    focus_compose_only = True  # Default to Focus Compose Root for best developer experience
    filter_query = ""

    def refresh_screen():
        nonlocal raw_root, active_root, status_msg
        try:
            resolve_composable_from_source.cache_clear()
            parse_kotlin_composable_chain.cache_clear()
            find_composable_definition.cache_clear()
            parse_composable_body_subnodes.cache_clear()
            
            path = fetch_ui_dump()
            tree = ET.parse(path)
            xml_root = tree.getroot()
            
            dummy = ET.Element("Screen")
            dummy.attrib["class"] = "RootWindow"
            for c in xml_root:
                dummy.append(c)
            
            raw_root = UINode(dummy, depth=0)
            raw_root.propagate_hierarchy()
            
            update_active_view()
            status_msg = f"Screen captured. Full Composable AST depth expanded. (Project: {os.path.basename(PROJECT_ROOT)})"
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
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        
        mode_tag = "[Focus: Compose]" if focus_compose_only else "[Focus: All Window]"
        header = f" [Compose Deep Inspector] {mode_tag}  [r]: Refresh  [f]: Toggle Root  [1-9]: Depth  [e/c]: Expand/Collapse  [q]: Quit "
        stdscr.addstr(0, 0, header[:w-1].ljust(w-1), curses.A_REVERSE | curses.A_BOLD)
        
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

        for row in range(view_height):
            item_idx = scroll_offset + row
            if item_idx >= total_items:
                break
            
            node = visible_items[item_idx]
            depth_tag = f"L{node.depth:02d} "
            indent = " " * (node.depth * 2)
            prefix = ("▼ " if node.expanded else "▶ ") if node.children else "• "
            
            line_str = f"{depth_tag}{indent}{prefix}{node.display_text()}"
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
        msg_color = curses.color_pair(3) if ("Opened" in status_msg or "captured" in status_msg) else curses.color_pair(4)
        stdscr.addstr(status_y, 0, f" Status: {status_msg}"[:w-1].ljust(w-1), msg_color | curses.A_BOLD)
        
        stdscr.refresh()

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            break

        if key in (ord('q'), ord('Q'), 17, 27):  # 'q', 'Q', Ctrl+Q, ESC
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
        elif key in (curses.KEY_RIGHT, ord('l')):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                if not node.expanded and node.children:
                    node.expanded = True
        elif key == ord(' '):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                node.expanded = not node.expanded
        elif key == ord('f'):
            focus_compose_only = not focus_compose_only
            update_active_view()
            status_msg = "Focused Compose application root." if focus_compose_only else "Showing full window hierarchy."
        elif ord('1') <= key <= ord('9'):
            target_depth = key - ord('0')
            set_expand_depth(active_root, 0, target_depth)
            status_msg = f"Expanded tree up to Depth L{target_depth}."
        elif key == ord('e'):
            set_expand_depth(active_root, 0, 999)
            status_msg = "Expanded all nodes to maximum depth."
        elif key == ord('c'):
            set_expand_depth(active_root, 0, 1)
            status_msg = "Collapsed tree to root level."
        elif key == ord('r'):
            status_msg = "Refreshing screen dump..."
            stdscr.addstr(status_y, 0, f" Status: {status_msg}"[:w-1].ljust(w-1), curses.A_BOLD)
            stdscr.refresh()
            refresh_screen()
        elif key in (curses.KEY_ENTER, 10, 13, ord('o')):
            if visible_items and cursor_idx < len(visible_items):
                node = visible_items[cursor_idx]
                if node.source_file and node.source_line:
                    status_msg = jump_to_ide(node.source_file, node.source_line)
                else:
                    status_msg = f"No source file found for {node.display_text()}"

def main():
    try:
        curses.wrapper(run_tui)
    except KeyboardInterrupt:
        pass
    sys.exit(0)

if __name__ == "__main__":
    main()
