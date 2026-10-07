"""Replace do-nothing wrapper frames and groups with their only child.

A wrapper is a FRAME or GROUP with one child that paints nothing, clips
nothing, applies no opacity, blend or rotation, and has no auto-layout of its
own. Inside an auto-layout parent it must also be the same box as its child,
because there the wrapper's size takes part in the flow. Requested roots are
never flattened.
"""

from __future__ import annotations

from typing import Any

from figma_fit.models import State
from figma_fit.passes.base import CHILDREN, plural

_WRAPPER_TYPES = {"FRAME", "GROUP"}
_PAINT_KEYS = ("fills", "strokes", "effects")
_BOX_TOLERANCE = 0.5


class FlattenWrappers:
    name = "flatten_wrappers"

    def __call__(self, state: State) -> tuple[State, str]:
        flattened = 0

        def visit(node: dict[str, Any]) -> dict[str, Any]:
            nonlocal flattened
            children = node.get(CHILDREN)
            if not children:
                return node
            in_flow = _has_auto_layout(node)
            new_children = []
            for child in children:
                while _is_wrapper(child, in_flow):
                    child = child[CHILDREN][0]
                    flattened += 1
                new_children.append(visit(child))
            return {**node, CHILDREN: new_children}

        roots = [visit(root) for root in state.data]
        note = f"−{plural(flattened, 'wrapper')}" if flattened else ""
        return State(roots, state.legend), note


def _is_wrapper(node: dict[str, Any], parent_in_flow: bool) -> bool:
    children = node.get(CHILDREN)
    if node.get("type") not in _WRAPPER_TYPES or not children or len(children) != 1:
        return False
    if any(_paints_something(node.get(key)) for key in _PAINT_KEYS):
        return False
    if node.get("clipsContent") or node.get("isMask"):
        return False
    if node.get("opacity", 1) != 1 or node.get("blendMode", "PASS_THROUGH") != "PASS_THROUGH":
        return False
    if node.get("rotation", 0) or _has_auto_layout(node):
        return False
    return not parent_in_flow or _same_box(node, children[0])


def _paints_something(paints: Any) -> bool:
    if not paints:
        return False
    if isinstance(paints, list):
        return any(not (isinstance(p, dict) and p.get("visible") is False) for p in paints)
    return True  # a style reference or anything unexpected: keep the wrapper


def _has_auto_layout(node: dict[str, Any]) -> bool:
    return node.get("layoutMode", "NONE") not in ("NONE", None)


def _same_box(a: dict[str, Any], b: dict[str, Any]) -> bool:
    box_a, box_b = a.get("absoluteBoundingBox"), b.get("absoluteBoundingBox")
    if not isinstance(box_a, dict) or not isinstance(box_b, dict):
        return False
    return all(
        abs(float(box_a.get(k, 0)) - float(box_b.get(k, 0))) <= _BOX_TOLERANCE
        for k in ("x", "y", "width", "height")
    )
