"""Remove what Figma would not render.

- nodes with ``visible: false`` or ``opacity: 0``
- nodes whose box lies fully outside a clipping ancestor; each requested root
  counts as clipping, since anything outside it is outside the selection
- paints and effects with ``visible: false``
"""

from __future__ import annotations

from typing import Any

from figma_fit.models import State
from figma_fit.passes.base import CHILDREN, count_nodes, plural

Box = tuple[float, float, float, float]  # x0, y0, x1, y1

_PAINT_KEYS = ("fills", "strokes", "effects")


class DropInvisible:
    name = "drop_invisible"

    def __call__(self, state: State) -> tuple[State, str]:
        counts = {"hidden": 0, "zero-opacity": 0, "clipped off-canvas": 0}
        stats = {"nodes": 0, "paints": 0}

        def visit(node: dict[str, Any], clip: Box | None) -> dict[str, Any]:
            out = dict(node)
            for key in _PAINT_KEYS:
                paints = node.get(key)
                if isinstance(paints, list):
                    kept = [p for p in paints if not _hidden_paint(p)]
                    if len(kept) != len(paints):
                        stats["paints"] += len(paints) - len(kept)
                        out[key] = kept

            box = _box(node)
            if node.get("clipsContent") and box is not None:
                clip = _intersect(clip, box) if clip else box

            children = node.get(CHILDREN)
            if children:
                kept_children = []
                for child in children:
                    reason = _drop_reason(child, clip)
                    if reason:
                        counts[reason] += 1
                        stats["nodes"] += count_nodes(child)
                    else:
                        kept_children.append(visit(child, clip))
                out[CHILDREN] = kept_children
            return out

        roots = [visit(root, _box(root)) for root in state.data]
        return State(roots, state.legend), _note(counts, stats)


def _hidden_paint(paint: Any) -> bool:
    return isinstance(paint, dict) and paint.get("visible") is False


def _drop_reason(node: dict[str, Any], clip: Box | None) -> str | None:
    if node.get("visible") is False:
        return "hidden"
    if node.get("opacity") == 0:
        return "zero-opacity"
    box = _box(node)
    if clip is not None and box is not None and not _overlaps(box, clip):
        return "clipped off-canvas"
    return None


def _box(node: dict[str, Any]) -> Box | None:
    b = node.get("absoluteBoundingBox")
    if not isinstance(b, dict):
        return None
    try:
        x, y, w, h = float(b["x"]), float(b["y"]), float(b["width"]), float(b["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y, x + w, y + h)


def _intersect(a: Box, b: Box) -> Box:
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _overlaps(a: Box, b: Box) -> bool:
    # Boxes that only touch at an edge do not overlap.
    strict = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    return strict or _degenerate_inside(a, b)


def _degenerate_inside(a: Box, b: Box) -> bool:
    # Zero-width or zero-height nodes (lines) still render when they lie inside the clip.
    zero = a[0] == a[2] or a[1] == a[3]
    return zero and b[0] <= a[0] <= b[2] and b[1] <= a[1] <= b[3]


def _note(counts: dict[str, int], stats: dict[str, int]) -> str:
    parts = []
    if stats["nodes"]:
        reasons = ", ".join(f"{n} {reason}" for reason, n in counts.items() if n)
        parts.append(f"−{plural(stats['nodes'], 'node')} ({reasons})")
    if stats["paints"]:
        parts.append(f"−{plural(stats['paints'], 'hidden paint')}")
    return ", ".join(parts)
