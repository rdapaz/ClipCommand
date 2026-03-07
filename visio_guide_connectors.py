#!/usr/bin/env python3
"""
visio_guide_connectors.py
─────────────────────────
Connects to the active Visio instance and places connection points on shapes
wherever page guides intersect their bounding boxes.

Usage:
    python visio_guide_connectors.py                   # selected shape(s) only
    python visio_guide_connectors.py --all-shapes      # every non-guide shape on page
    python visio_guide_connectors.py --cleanup         # also remove stale points
    python visio_guide_connectors.py --dry-run -v      # preview without modifying

Modes (can be combined freely):
    (default)       Process the currently-selected shape(s).
    --all-shapes    Process every non-guide shape on the active page.
    --cleanup       After adding new points, remove any connection points that
                    do NOT align to any guide.  Off by default.
    --min-size N    Skip shapes whose width OR height is below N inches.
                    Default 1.0.  Use 0 to disable the filter entirely.
    --dry-run       Report all changes without writing anything to Visio.
    --verbose / -v  Print per-shape, per-guide detail.

Requirements:
    pip install pywin32
"""

import sys
import math
import argparse

# ── Visio ShapeSheet constants (numeric — avoids typelib dependency) ──────────
VIS_SECTION_CONNECTIONPTS = 7    # visSectionConnectionPts
VIS_ROW_CONNECTIONPTS     = 0    # visRowConnectionPts
VIS_TAG_CNNCTPT           = 153  # visTagCnnctPt
VIS_CELL_X                = 0
VIS_CELL_Y                = 1
VIS_TYPE_GUIDE            = 5    # visTypeGuide

# Tolerances (inches)
EDGE_TOLERANCE      = 0.001   # how close a guide must be to the shape boundary
DUPLICATE_TOLERANCE = 0.01    # don't add a point within this distance of an existing one
STALE_TOLERANCE     = 0.01    # cleanup: point must be within this distance of a guide


# ── Guide helpers ─────────────────────────────────────────────────────────────

def get_guide_info(guide):
    """
    Return (position_in, is_vertical) for a Visio guide shape.

    Guides are degenerate shapes:
      - Vertical guide   → Height ≈ 0, position = PinX
      - Horizontal guide → Width  ≈ 0, position = PinY
    """
    try:
        w = guide.Cells("Width").ResultIU
        h = guide.Cells("Height").ResultIU
    except Exception:
        w, h = 0.0, 0.0

    is_vertical = h < 0.001

    try:
        pos = guide.Cells("PinX").ResultIU if is_vertical else guide.Cells("PinY").ResultIU
    except Exception:
        pos = 0.0

    return pos, is_vertical


def collect_guides(page):
    """Return a list of all guide shapes on *page*."""
    guides = []
    for i in range(1, page.Shapes.Count + 1):
        try:
            s = page.Shapes.Item(i)
            if s.Type == VIS_TYPE_GUIDE:
                guides.append(s)
        except Exception:
            pass
    return guides


# ── Shape geometry helpers ────────────────────────────────────────────────────

def get_shape_bbox(shape):
    """
    Return (left, bottom, right, top, width, height) in page inches.
    Honours non-centred LocPinX/Y.
    """
    pin_x  = shape.Cells("PinX").ResultIU
    pin_y  = shape.Cells("PinY").ResultIU
    width  = shape.Cells("Width").ResultIU
    height = shape.Cells("Height").ResultIU
    loc_x  = shape.Cells("LocPinX").ResultIU
    loc_y  = shape.Cells("LocPinY").ResultIU

    left   = pin_x - loc_x
    bottom = pin_y - loc_y
    right  = left   + width
    top    = bottom + height

    return left, bottom, right, top, width, height


def page_to_relative(page_val, origin, dimension):
    """Convert an absolute page coordinate to a 0–1 fraction within a shape."""
    return 0.5 if dimension == 0 else (page_val - origin) / dimension


# ── Connection-point helpers ──────────────────────────────────────────────────

def get_existing_connection_points(shape):
    """
    Return list of (row_index, abs_x, abs_y) for all existing connection points,
    where abs_x/abs_y are absolute page coordinates in inches.

    Connection point cells store formulas like "=Width*0.515" so ResultIU gives
    the value in shape-local inches (relative to the shape origin).  We convert
    to page coordinates by adding the shape's left/bottom offsets.
    """
    pts = []
    try:
        left, bottom, right, top, width, height = get_shape_bbox(shape)
        section = shape.Section(VIS_SECTION_CONNECTIONPTS)
        for row_idx in range(section.Count):
            row   = section.Row(row_idx)
            loc_x = row.Cell(VIS_CELL_X).ResultIU   # shape-local inches
            loc_y = row.Cell(VIS_CELL_Y).ResultIU
            abs_x = left   + loc_x
            abs_y = bottom + loc_y
            pts.append((row_idx, abs_x, abs_y))
    except Exception:
        pass
    return pts


def is_near(rel_x, rel_y, ex, ey, width, height, tol):
    """True if two relative points are within *tol* inches of each other."""
    return math.hypot((rel_x - ex) * width, (rel_y - ey) * height) < tol


def ensure_connection_section(shape):
    if not shape.SectionExists(VIS_SECTION_CONNECTIONPTS, 1):
        shape.AddSection(VIS_SECTION_CONNECTIONPTS)


def add_connection_point(shape, rel_x, rel_y):
    """Add one resize-safe connection point at (rel_x, rel_y)."""
    ensure_connection_section(shape)
    row = shape.AddRow(VIS_SECTION_CONNECTIONPTS, VIS_ROW_CONNECTIONPTS, VIS_TAG_CNNCTPT)
    shape.CellsSRC(VIS_SECTION_CONNECTIONPTS, row, VIS_CELL_X).FormulaU = f"=Width*{rel_x:.6f}"
    shape.CellsSRC(VIS_SECTION_CONNECTIONPTS, row, VIS_CELL_Y).FormulaU = f"=Height*{rel_y:.6f}"


# ── Stale-point detection ─────────────────────────────────────────────────────

def find_stale_rows_from_snapshot(snapshot, guides):
    """
    Return row indices (descending, for safe deletion) of pre-existing connection
    points that do not align with any current guide.

    snapshot is [(row_idx, abs_x, abs_y), ...] in absolute page inches.
    A point is aligned when abs_x matches a vertical guide, or abs_y matches a
    horizontal guide, within STALE_TOLERANCE.
    """
    stale = []
    for row_idx, abs_x, abs_y in snapshot:
        aligned = False
        for guide in guides:
            pos, is_vertical = get_guide_info(guide)
            if is_vertical and abs(abs_x - pos) < STALE_TOLERANCE:
                aligned = True
                break
            if not is_vertical and abs(abs_y - pos) < STALE_TOLERANCE:
                aligned = True
                break
        if not aligned:
            stale.append(row_idx)
    return sorted(stale, reverse=True)


# ── Core per-shape processor ──────────────────────────────────────────────────

def process_shape(shape, guides, dry_run=False, verbose=False, cleanup=False, min_size=1.0):
    """
    Add connection points at guide intersections.
    Optionally remove stale points when cleanup=True.
    Skips shapes whose width or height is below min_size inches (0 = no filter).
    Returns (added_count, removed_count).
    """
    try:
        left, bottom, right, top, width, height = get_shape_bbox(shape)
    except Exception as exc:
        if verbose:
            print(f"  Skipping — bbox error: {exc}")
        return 0, 0

    label = shape.Text or f"<shape {shape.ID}>"

    # ── Size filter ───────────────────────────────────────────────────────────
    if min_size > 0 and (width < min_size or height < min_size):
        if verbose:
            print(f"\nShape: \"{label}\"  SKIPPED (W={width:.3f} H={height:.3f} < min {min_size})")
        return 0, 0
    if verbose:
        print(f"\nShape: \"{label}\"")
        print(f"  Bbox  L={left:.3f}  B={bottom:.3f}  R={right:.3f}  T={top:.3f}"
              f"  W={width:.3f}  H={height:.3f}")

    # ── 1. Snapshot pre-existing connection points ────────────────────────────
    existing_snapshot = get_existing_connection_points(shape)  # [(row_idx, abs_x, abs_y), ...]
    existing_abs = [(ax, ay) for _, ax, ay in existing_snapshot]
    added = 0

    # ── 2. Add new connection points ──────────────────────────────────────────
    for guide in guides:
        pos, is_vertical = get_guide_info(guide)

        if is_vertical:
            if not (left - EDGE_TOLERANCE <= pos <= right + EDGE_TOLERANCE):
                if verbose:
                    print(f"  Guide X={pos:.3f}  MISS  (shape X {left:.3f}–{right:.3f})")
                continue
            rel_x      = max(0.0, min(1.0, page_to_relative(pos, left, width)))
            candidates = [(rel_x, 0.0), (rel_x, 1.0)]
            desc       = f"Vertical   X={pos:.3f}"
        else:
            if not (bottom - EDGE_TOLERANCE <= pos <= top + EDGE_TOLERANCE):
                if verbose:
                    print(f"  Guide Y={pos:.3f}  MISS  (shape Y {bottom:.3f}–{top:.3f})")
                continue
            rel_y      = max(0.0, min(1.0, page_to_relative(pos, bottom, height)))
            candidates = [(0.0, rel_y), (1.0, rel_y)]
            desc       = f"Horizontal Y={pos:.3f}"

        for rel_x, rel_y in candidates:
            # Convert candidate to absolute for duplicate check
            cand_abs_x = left   + rel_x * width
            cand_abs_y = bottom + rel_y * height
            if any(math.hypot(cand_abs_x - ax, cand_abs_y - ay) < DUPLICATE_TOLERANCE
                   for ax, ay in existing_abs):
                if verbose:
                    print(f"  Guide {desc}  → duplicate skipped  ({rel_x:.3f}, {rel_y:.3f})")
                continue

            if verbose:
                action = "[DRY RUN] would add" if dry_run else "Adding"
                print(f"  Guide {desc}  → {action} point  ({rel_x:.3f}, {rel_y:.3f})")

            if not dry_run:
                add_connection_point(shape, rel_x, rel_y)
                existing_abs.append((cand_abs_x, cand_abs_y))
            added += 1

    # ── 3. Remove stale points (--cleanup) ────────────────────────────────────
    removed = 0
    if cleanup:
        stale_rows = find_stale_rows_from_snapshot(existing_snapshot, guides)
        for row_idx in stale_rows:
            if verbose:
                action = "[DRY RUN] would remove" if dry_run else "Removing"
                print(f"  Cleanup  → {action} stale point at row {row_idx}")
            if not dry_run:
                try:
                    shape.DeleteRow(VIS_SECTION_CONNECTIONPTS, row_idx)
                    removed += 1
                except Exception as exc:
                    if verbose:
                        print(f"    (deletion failed: {exc})")
            else:
                removed += 1

    return added, removed


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Add Visio connection points where page guides intersect shape boundaries.\n"
            "Default: processes selected shape(s).  Use --all-shapes for the whole page."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--all-shapes", action="store_true",
        help="Process every non-guide shape on the page (ignores current selection)."
    )
    ap.add_argument(
        "--min-size", type=float, default=1.0, metavar="N",
        help="Skip shapes smaller than N inches in either dimension (default: 1.0). "
             "Use 0 to disable."
    )
    ap.add_argument(
        "--cleanup", action="store_true",
        help="Also remove connection points that no longer align to any guide."
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without modifying the drawing."
    )
    ap.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-shape and per-guide detail."
    )
    args = ap.parse_args()

    # ── Connect to Visio ──────────────────────────────────────────────────────
    try:
        import win32com.client
    except ImportError:
        sys.exit("ERROR: pywin32 not installed.  Run:  pip install pywin32")

    try:
        visio = win32com.client.GetActiveObject("Visio.Application")
    except Exception:
        sys.exit("ERROR: No active Visio instance found.  Open a drawing first.")

    try:
        page = visio.ActivePage
    except Exception:
        sys.exit("ERROR: Could not access the active Visio page.")

    # ── Gather guides ─────────────────────────────────────────────────────────
    guides = collect_guides(page)
    if not guides:
        sys.exit("INFO: No guides on the active page — nothing to do.")

    if args.verbose:
        print(f"Page: \"{page.Name}\"  |  Guides: {len(guides)}")
        for g in guides:
            pos, is_vert = get_guide_info(g)
            print(f"  {'Vertical  X' if is_vert else 'Horizontal Y'} = {pos:.4f} in")

    # ── Determine target shapes ───────────────────────────────────────────────
    if args.all_shapes:
        shapes = []
        for i in range(1, page.Shapes.Count + 1):
            try:
                s = page.Shapes.Item(i)
                if s.Type != VIS_TYPE_GUIDE:
                    shapes.append(s)
            except Exception:
                pass
        print(f"Mode: all shapes  ({len(shapes)} shapes on page)")
    else:
        selection = visio.ActiveWindow.Selection
        if selection.Count == 0:
            sys.exit("ERROR: Nothing selected.  Select shape(s) or use --all-shapes.")
        shapes = [selection.Item(i) for i in range(1, selection.Count + 1)]
        noun = "shape" if len(shapes) == 1 else "shapes"
        print(f"Mode: selection  ({len(shapes)} {noun} selected)")

    if args.dry_run:
        print("*** DRY RUN — no changes will be written ***")
    if args.cleanup:
        print("Cleanup enabled — stale connection points will be removed.")
    if args.min_size > 0:
        print(f"Size filter: skipping shapes smaller than {args.min_size} in either dimension.")

    # ── Process ───────────────────────────────────────────────────────────────
    total_added = total_removed = total_skipped = 0

    for shape in shapes:
        try:
            added, removed = process_shape(
                shape, guides,
                dry_run=args.dry_run,
                verbose=args.verbose,
                cleanup=args.cleanup,
                min_size=args.min_size,
            )
            total_added   += added
            total_removed += removed
        except Exception as exc:
            total_skipped += 1
            if args.verbose:
                print(f"  ERROR on shape {shape.ID}: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    tag = " (dry run)" if args.dry_run else ""
    print(f"\n── Summary{tag} {'─' * 35}")
    print(f"  Shapes processed : {len(shapes) - total_skipped}")
    print(f"  Points added     : {total_added}")
    if args.cleanup:
        print(f"  Points removed   : {total_removed}")
    if total_skipped:
        print(f"  Shapes skipped   : {total_skipped}  (use -v for detail)")
    print()


if __name__ == "__main__":
    main()