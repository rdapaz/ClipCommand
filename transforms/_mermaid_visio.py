#!/usr/bin/env python3
"""
Mermaid-to-Visio helper module.

Contains the parser, layout engines, and Visio generator extracted from
the original mermaid_to_visio.py CLI tool.  Imported by the ClipCommand
transform; not loaded directly by the transform scanner (leading underscore).

Windows only — requires win32com (pywin32).
"""

import re
import os
import math
from collections import defaultdict, deque

# ── Page / shape geometry (inches, Visio coordinate system) ───────────────────

A4_WIDTH  = 11.70   # landscape
A4_HEIGHT =  8.27

MARGIN             = 0.5
SHAPE_WIDTH        = 1.5
SHAPE_HEIGHT       = 0.75
HORIZONTAL_SPACING = 0.5
VERTICAL_SPACING   = 0.75

# Defaults exposed so the transform can reference them in its docstring
DEFAULT_HORIZONTAL_CONNECTIONS = 5
DEFAULT_VERTICAL_CONNECTIONS   = 3

# Visio ShapeSheet section / row / cell constants (numeric to avoid typelib issues)
VIS_SECTION_CONNECTIONPTS = 7    # visSectionConnectionPts
VIS_ROW_CONNECTIONPTS     = 0    # visRowConnectionPts
VIS_TAG_CNNCTPT           = 153  # visTagCnnctPt
VIS_CELL_X                = 0
VIS_CELL_Y                = 1


# ── Mermaid parser ────────────────────────────────────────────────────────────

class MermaidParser:
    """Parse Mermaid flowchart / graph syntax into nodes and edges."""

    def __init__(self, mermaid_text: str):
        self.text   = mermaid_text
        self.nodes  = {}   # node_id -> label
        self.edges  = []   # [(from_id, to_id), ...]
        self.groups = {}   # node_id -> subgraph name

    # ── helpers ───────────────────────────────────────────────────────────────

    def _clean_label(self, label):
        if label is None:
            return None
        s = label.strip()
        if len(s) >= 2 and (
            (s[0] == '"' and s[-1] == '"') or
            (s[0] == "'" and s[-1] == "'")
        ):
            s = s[1:-1].strip()
        return s

    def _register_node(self, node_id, label, current_group=None):
        if label is not None:
            label = self._clean_label(label)
        if label:
            self.nodes.setdefault(node_id, label)
        else:
            self.nodes.setdefault(node_id, node_id)
        if current_group is not None and node_id not in self.groups:
            self.groups[node_id] = current_group

    # ── public ────────────────────────────────────────────────────────────────

    def parse(self):
        """Return (nodes dict, edges list).  Raises ValueError on empty result."""
        lines = self.text.strip().split('\n')

        in_front_matter = False
        current_group   = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # YAML front-matter fences
            if line.startswith('---'):
                in_front_matter = not in_front_matter
                continue
            if in_front_matter:
                continue

            # Diagram type declarations and comments
            if (line.startswith('graph') or line.startswith('flowchart')
                    or line.startswith('%')):
                continue

            # Subgraph tracking
            if line.startswith('subgraph '):
                m = re.match(r'subgraph\s+([A-Za-z0-9_]+)', line)
                current_group = m.group(1) if m else None
                continue
            if line == 'end':
                current_group = None
                continue

            # Styling / class definitions
            if line.startswith('classDef ') or line.startswith('class '):
                continue
            if ':::' in line:
                continue

            # Strip inline comments
            if '%%' in line:
                line = line.split('%%', 1)[0].strip()
                if not line:
                    continue

            # ── Arrow normalisation ───────────────────────────────────────

            # "A -- label --> B"  →  "A --> B"
            line = re.sub(r'(\w+(?:\[.*?\])?)\s--[^>]+-->', r'\1 -->', line)
            # "A -. label .-> B"  →  "A --> B"
            line = re.sub(r'(\w+(?:\[.*?\])?)\s-\.[^>]+\.->',  r'\1 -->', line)
            # undirected ---  →  -->
            line = line.replace('---', '-->')
            # all remaining arrow variants  →  -->
            line = re.sub(r'[-\.]{2,}>', '-->', line)

            # ── Edge / node patterns ─────────────────────────────────────

            # 1) Labelled edge:  A -->|label| B
            m = re.search(
                r'(\w+)(?:\[([^\]]+)\])?\s*-->\|([^\|]+)\|\s*(\w+)(?:\[([^\]]+)\])?',
                line
            )
            if m:
                self._register_node(m.group(1), m.group(2), current_group)
                self._register_node(m.group(4), m.group(5), current_group)
                self.edges.append((m.group(1), m.group(4)))
                continue

            # 2) Multi-target:  A --> B & C & D["Label"]
            if '&' in line and '-->' in line:
                m = re.search(r'(\w+)(?:\[([^\]]+)\])?\s*-->\s*(.+)', line)
                if m:
                    from_id = m.group(1)
                    self._register_node(from_id, m.group(2), current_group)
                    for part in m.group(3).split('&'):
                        part = part.strip()
                        if not part:
                            continue
                        nm = re.match(r'(\w+)(?:\[([^\]]+)\])?', part)
                        if nm:
                            self._register_node(nm.group(1), nm.group(2), current_group)
                            self.edges.append((from_id, nm.group(1)))
                    continue

            # 3) Standard single-target:  A[Label] --> B[Label]
            m = re.search(
                r'(\w+)(?:\[([^\]]+)\])?\s*-->\s*(\w+)(?:\[([^\]]+)\])?',
                line
            )
            if m:
                self._register_node(m.group(1), m.group(2), current_group)
                self._register_node(m.group(3), m.group(4), current_group)
                self.edges.append((m.group(1), m.group(3)))
                continue

            # 4) Standalone node:  A[Label]
            m = re.search(r'(\w+)\[([^\]]+)\]', line)
            if m:
                self._register_node(m.group(1), m.group(2), current_group)
                continue

        if not self.nodes:
            raise ValueError(
                "No valid Mermaid nodes found. "
                "Expected syntax like:  A[Label] --> B[Label]"
            )

        return self.nodes, self.edges


# ── Layout engines ────────────────────────────────────────────────────────────

class FlowLayoutEngine:
    """Hierarchical top-to-bottom layout using BFS level assignment."""

    def __init__(self, nodes, edges, width, height, groups=None):
        self.nodes  = nodes
        self.edges  = edges
        self.width  = width
        self.height = height
        self.groups = groups or {}

    def _calculate_levels(self):
        incoming = defaultdict(int)
        outgoing = defaultdict(list)
        for from_id, to_id in self.edges:
            incoming[to_id] += 1
            outgoing[from_id].append(to_id)

        roots = [n for n in self.nodes if incoming[n] == 0] or list(self.nodes)

        levels  = {}
        queue   = deque((r, 0) for r in roots)
        visited = set()
        while queue:
            node_id, level = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            levels[node_id] = level
            for child in outgoing[node_id]:
                if child not in visited:
                    queue.append((child, level + 1))

        for node_id in self.nodes:
            levels.setdefault(node_id, 0)

        return levels

    def layout(self):
        levels = self._calculate_levels()
        level_groups = defaultdict(list)
        for node_id, level in levels.items():
            level_groups[level].append(node_id)

        max_level    = max(levels.values()) if levels else 0
        usable_width = self.width  - 2 * MARGIN
        usable_height= self.height - 2 * MARGIN
        positions    = {}

        for level in range(max_level + 1):
            nodes_at_level = sorted(
                level_groups[level],
                key=lambda nid: self.groups.get(nid, "")
            )
            n = len(nodes_at_level)
            if n == 0:
                continue

            y_pos = (self.height / 2 if max_level == 0
                     else self.height - MARGIN - (level / max_level) * usable_height)

            if n == 1:
                x_positions = [self.width / 2]
            else:
                spacing = usable_width / (n + 1)
                x_positions = [MARGIN + (i + 1) * spacing for i in range(n)]

            for i, node_id in enumerate(nodes_at_level):
                positions[node_id] = (x_positions[i], y_pos)

        return positions


class HilbertLayoutEngine:
    """Space-filling Hilbert-curve layout."""

    def __init__(self, nodes, edges, width, height):
        self.nodes  = nodes
        self.edges  = edges
        self.width  = width
        self.height = height

    def _d2xy(self, n, d):
        x = y = 0
        s = 1
        while s < n:
            rx = 1 & (d // 2)
            ry = 1 & (d ^ rx)
            x, y = self._rot(s, x, y, rx, ry)
            x += s * rx
            y += s * ry
            d //= 4
            s *= 2
        return x, y

    def _rot(self, n, x, y, rx, ry):
        if ry == 0:
            if rx == 1:
                x = n - 1 - x
                y = n - 1 - y
            x, y = y, x
        return x, y

    def layout(self):
        num_nodes     = len(self.nodes)
        n             = 2 ** math.ceil(math.log2(math.sqrt(max(num_nodes, 1))))
        usable_width  = self.width  - 2 * MARGIN - SHAPE_WIDTH
        usable_height = self.height - 2 * MARGIN - SHAPE_HEIGHT
        positions     = {}

        for i, node_id in enumerate(self.nodes):
            hx, hy = self._d2xy(n, i)
            x = MARGIN + SHAPE_WIDTH  / 2 + (hx / n) * usable_width
            y = MARGIN + SHAPE_HEIGHT / 2 + (hy / n) * usable_height
            positions[node_id] = (x, y)

        return positions


# ── Visio generator ───────────────────────────────────────────────────────────

class VisioGenerator:
    """Generate a Visio document from parsed nodes and layout positions."""

    def __init__(self,
                 layout_engine: str = 'flow',
                 horizontal_connections: int = DEFAULT_HORIZONTAL_CONNECTIONS,
                 vertical_connections:   int = DEFAULT_VERTICAL_CONNECTIONS):
        self.layout_engine           = layout_engine
        self.horizontal_connections  = horizontal_connections
        self.vertical_connections    = vertical_connections
        self.visio            = None
        self.doc              = None
        self.page             = None
        self.master_shapes    = {}
        self.stencil          = None
        self.rectangle_master = None

    # ── Visio document setup ──────────────────────────────────────────────────

    def _create_document(self):
        import win32com.client
        self.visio = win32com.client.Dispatch("Visio.Application")
        self.visio.Visible = True
        self.doc  = self.visio.Documents.Add("")
        self.page = self.doc.Pages.Item(1)
        self.page.PageSheet.CellsSRC(1, 0, 0).FormulaU = f"{A4_WIDTH} in"
        self.page.PageSheet.CellsSRC(1, 0, 1).FormulaU = f"{A4_HEIGHT} in"

    # ── Rectangle / stencil helpers ───────────────────────────────────────────

    def _find_rectangle_master(self):
        if self.rectangle_master:
            return self.rectangle_master

        for stencil_name in ("BASFLO_M.VSSX", "BASIC_U.VSSX", "BASFLO_U.VSSX"):
            try:
                basic_stencil = self.visio.Documents.OpenEx(stencil_name, 4)
                self.stencil = basic_stencil
                break
            except Exception:
                stencil_path = os.path.join(
                    os.path.dirname(self.visio.Path), stencil_name
                )
                if os.path.exists(stencil_path):
                    try:
                        self.stencil = self.visio.Documents.OpenEx(stencil_path, 4)
                        break
                    except Exception:
                        pass

        if not self.stencil:
            return None

        for name in ("Rectangle", "Process", "Box", "Square"):
            try:
                self.rectangle_master = self.stencil.Masters(name)
                return self.rectangle_master
            except Exception:
                pass

        return None

    def _create_rect(self, x, y):
        if self.rectangle_master is None:
            self._find_rectangle_master()
        if self.rectangle_master:
            return self.page.Drop(self.rectangle_master, x, y)
        x1, y1 = x - SHAPE_WIDTH / 2, y - SHAPE_HEIGHT / 2
        x2, y2 = x + SHAPE_WIDTH / 2, y + SHAPE_HEIGHT / 2
        return self.page.DrawRectangle(x1, y1, x2, y2)

    # ── Connection point helpers ──────────────────────────────────────────────

    def _ensure_connection_section(self, shape):
        if not shape.SectionExists(VIS_SECTION_CONNECTIONPTS, 1):
            shape.AddSection(VIS_SECTION_CONNECTIONPTS)

    def _add_connection_points_side(self, shape, count, horizontal):
        """
        Add evenly-spaced connection points along one pair of opposite edges.

        horizontal=False  →  left / right edges  (Y varies)
        horizontal=True   →  top  / bottom edges  (X varies)
        """
        count = int(count)
        if count <= 0:
            return
        self._ensure_connection_section(shape)

        denom = 2 * count
        for i in range(1, count + 1):
            for j in (1, 2):   # two opposite sides
                row = shape.AddRow(
                    VIS_SECTION_CONNECTIONPTS,
                    VIS_ROW_CONNECTIONPTS,
                    VIS_TAG_CNNCTPT
                )
                if not horizontal:
                    y_formula = f"={i}*(Height/{count}) - Height/{denom}"
                    x_formula = "=Width*0" if j == 1 else "=Width*1"
                else:
                    x_formula = f"={i}*(Width/{count}) - Width/{denom}"
                    y_formula = "=Height*0" if j == 1 else "=Height*1"

                shape.CellsSRC(VIS_SECTION_CONNECTIONPTS, row, VIS_CELL_X).FormulaU = x_formula
                shape.CellsSRC(VIS_SECTION_CONNECTIONPTS, row, VIS_CELL_Y).FormulaU = y_formula

    def _add_connection_points(self, shape, h_count, v_count):
        if v_count > 0:
            self._add_connection_points_side(shape, v_count, horizontal=False)
        if h_count > 0:
            self._add_connection_points_side(shape, h_count, horizontal=True)

    # ── Master shape ──────────────────────────────────────────────────────────

    def _create_master_shape(self):
        if "master" in self.master_shapes:
            return self.master_shapes["master"]

        page_height = self.page.PageSheet.Cells("PageHeight").ResultIU
        mx = MARGIN + SHAPE_WIDTH  / 2
        my = page_height - MARGIN  - SHAPE_HEIGHT / 2

        s = self._create_rect(mx, my)
        s.Text = "MASTER"
        try:
            s.Cells("Width").FormulaForce  = f"{SHAPE_WIDTH} in"
            s.Cells("Height").FormulaForce = f"{SHAPE_HEIGHT} in"
        except Exception:
            pass
        try:
            s.Cells("LineWeight").FormulaU = "3 pt"
        except Exception:
            pass

        self._add_connection_points(s, self.horizontal_connections, self.vertical_connections)
        self.master_shapes["master"] = s
        return s

    def _link_to_master(self, shape, master):
        name = master.Name
        try:
            shape.Cells("Width").FormulaForce  = f"GUARD({name}!Width)"
            shape.Cells("Height").FormulaForce = f"GUARD({name}!Height)"
        except Exception:
            pass

    # ── Shape creation ────────────────────────────────────────────────────────

    def _create_shapes(self, nodes, positions):
        master = self._create_master_shape()
        shape_map = {}

        for node_id, label in nodes.items():
            if node_id not in positions:
                continue
            x, y  = positions[node_id]
            shape = self._create_rect(x, y)
            shape.Text = label
            self._link_to_master(shape, master)
            self._add_connection_points(shape, self.horizontal_connections, self.vertical_connections)
            shape_map[node_id] = shape

        return shape_map

    # ── Public entry point ────────────────────────────────────────────────────

    def generate(self, mermaid_text: str) -> dict:
        """
        Parse *mermaid_text*, lay out nodes, open Visio and populate the page.
        Returns the shape_map {node_id: Shape}.
        Raises ValueError for bad Mermaid syntax, ImportError if win32com missing.
        """
        parser = MermaidParser(mermaid_text)
        nodes, edges = parser.parse()

        if self.layout_engine == 'hilbert':
            layout = HilbertLayoutEngine(nodes, edges, A4_WIDTH, A4_HEIGHT)
        else:
            layout = FlowLayoutEngine(nodes, edges, A4_WIDTH, A4_HEIGHT,
                                      groups=parser.groups)

        positions = layout.layout()
        self._create_document()
        shape_map = self._create_shapes(nodes, positions)
        return shape_map
