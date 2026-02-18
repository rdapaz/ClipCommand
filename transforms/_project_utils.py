#!/usr/bin/env python3
"""
_project_utils.py — Microsoft Project automation helpers for ClipCommand.

Extracted from YAMLtoGantt.py (Ric de Paz).
Prefixed with _ so ClipCommand's transform scanner skips it.

Provides:
    OrderedDictYAMLLoader   — YAML loader that preserves key order
    MicrosoftProject        — COM wrapper around MSProject.Application
    populate_project        — convenience entry point used by transforms
"""

from collections import OrderedDict
import time
import yaml
import yaml.constructor

try:
    from dateutil.parser import parse as dateutil_parse
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False

try:
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


# ── YAML loader that preserves insertion order ────────────────────────────────

class OrderedDictYAMLLoader(yaml.Loader):
    """YAML loader that loads mappings into OrderedDicts, preserving key order."""

    def __init__(self, *args, **kwargs):
        yaml.Loader.__init__(self, *args, **kwargs)
        self.add_constructor(
            'tag:yaml.org,2002:map',  type(self).construct_yaml_map)
        self.add_constructor(
            'tag:yaml.org,2002:omap', type(self).construct_yaml_map)

    def construct_yaml_map(self, node):
        data = OrderedDict()
        yield data
        data.update(self.construct_mapping(node))

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
        else:
            raise yaml.constructor.ConstructorError(
                None, None,
                f'expected a mapping node, but found {node.id}',
                node.start_mark
            )
        mapping = OrderedDict()
        for key_node, value_node in node.value:
            key   = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    'while constructing a mapping', key_node.start_mark,
                    f'found unacceptable key ({exc})', key_node.start_mark
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


# ── Date helpers ──────────────────────────────────────────────────────────────

def _parse_date(date_string):
    if not DATEUTIL_AVAILABLE:
        raise ImportError("python-dateutil is required. pip install python-dateutil")
    try:
        return dateutil_parse(date_string)
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {date_string!r}. {exc}") from exc


def _is_date_like(string):
    if not DATEUTIL_AVAILABLE:
        return False
    try:
        dateutil_parse(string)
        return True
    except ValueError:
        return False


# ── Microsoft Project COM wrapper ─────────────────────────────────────────────

class MicrosoftProject:
    """
    Thin COM wrapper around MSProject.Application.
    Opens an existing .mpp file (local path or SharePoint URL) and appends
    tasks generated from a YAML-derived OrderedDict structure.
    """

    def __init__(self, doc_path: str):
        if not WIN32_AVAILABLE:
            raise EnvironmentError(
                "pywin32 is not installed. pip install pywin32\n"
                "Microsoft Project automation is Windows-only."
            )
        self._file     = doc_path
        self._app      = win32com.client.Dispatch('MSProject.Application')
        self._app.Visible = True
        self._app.FileOpen(self._file)
        self._proj     = self._app.ActiveProject
        self._task_ids = []   # [(task_id, nesting_level)]

    # ── Task creation ─────────────────────────────────────────────────────────

    def add_summary_task(self, task_name: str, nesting: int):
        tsk = self._proj.Tasks.Add(Name=task_name)
        nesting += 1
        tsk.Manual  = False
        tsk.Text2   = nesting
        self._set_outline_level(tsk, nesting)

    def add_auto_task(self, task_name: str, nesting: int,
                      duration: str = None, resources: str = None):
        tsk = self._proj.Tasks.Add(Name=task_name)
        nesting += 1
        tsk.Manual = False
        if duration:
            tsk.Duration = duration
        if resources:
            tsk.ResourceNames = resources
        tsk.Text2 = nesting

        # Link to previous sibling at same level with 50% overlap
        if self._task_ids and self._task_ids[-1][1] == nesting:
            tsk.Predecessors = f'{self._task_ids[-1][0]}FS-50%'

        self._set_outline_level(tsk, nesting)
        self._task_ids.append([tsk.ID, nesting])

    def add_manual_task(self, task_name: str, nesting: int,
                        start: str, finish: str):
        tsk = self._proj.Tasks.Add(Name=task_name)
        nesting += 1
        tsk.Manual = True
        tsk.Text2  = nesting

        start_dt  = _parse_date(start)
        finish_dt = _parse_date(finish)
        try:
            tsk.Start  = start_dt
            tsk.Finish = finish_dt
        except Exception as exc:
            raise RuntimeError(
                f"Error setting dates for '{task_name}': {exc}\n"
                f"  Start={start_dt}  Finish={finish_dt}"
            ) from exc

        self._set_outline_level(tsk, nesting)

    @staticmethod
    def _set_outline_level(tsk, target_level: int):
        while int(tsk.OutlineLevel) < target_level:
            tsk.OutlineIndent()
        while int(tsk.OutlineLevel) > target_level:
            tsk.OutlineOutdent()

    # ── Recursive YAML walker ─────────────────────────────────────────────────

    def yaml_to_gantt(self, obj: OrderedDict, nesting: int = 0):
        self._app.ScreenUpdating = False
        try:
            for task, rest in obj.items():
                if isinstance(rest, OrderedDict):
                    # Mapping value → summary / parent task
                    self.add_summary_task(task_name=task, nesting=nesting)
                    self.yaml_to_gantt(rest, nesting + 1)
                else:
                    # Scalar value → leaf task
                    val = str(rest).split('|', 1)[0].strip()
                    if _is_date_like(val):
                        # "start_date|finish_date" → manual fixed-date task
                        parts  = str(rest).split('|', 1)
                        start  = parts[0].strip()
                        finish = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                        self.add_manual_task(
                            task_name=task, nesting=nesting,
                            start=start, finish=finish
                        )
                    else:
                        # "duration|resources" → auto-scheduled task
                        parts = str(rest).split('|', 1)
                        duration  = parts[0].strip()
                        resources = parts[1].strip() if len(parts) > 1 else ""
                        self.add_auto_task(
                            task_name=task, nesting=nesting,
                            duration=duration, resources=resources
                        )
        finally:
            self._app.ScreenUpdating = True


# ── Convenience entry point ───────────────────────────────────────────────────

def populate_project(yaml_text: str, mpp_path: str) -> str:
    """
    Parse YAML text and populate an open MS Project file.
    Returns a status string.
    Raises on any error so the caller (transform) can format it cleanly.
    """
    try:
        data = yaml.load(yaml_text, Loader=OrderedDictYAMLLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error: {exc}") from exc

    if not isinstance(data, OrderedDict):
        raise ValueError("YAML must be a mapping at the top level.")

    start = time.time()
    pj    = MicrosoftProject(mpp_path)
    pj.yaml_to_gantt(data)
    elapsed = time.time() - start

    task_count = sum(1 for _ in _walk(data))
    return f"{task_count} task(s) added in {elapsed:.1f}s"


def _walk(obj):
    """Yield all leaf tasks recursively — used only for counting."""
    for _, v in obj.items():
        if isinstance(v, OrderedDict):
            yield from _walk(v)
        else:
            yield v
