"""Collapse repeated component instances to a reference plus a diff.

Sibling INSTANCE nodes with the same component, the same component
properties and the same size are compared with the first of them. When their
subtrees have the same shape, each later one becomes::

    {"id": "12:7", "name": "Row", "type": "INSTANCE", "sameAs": "12:6",
     "absoluteBoundingBox": {...}, "diff": {"/children/0/characters": "$29"}}

Diff keys are JSON pointers into the reference. Descendant ids are left out
(an instance sublayer id is "I<instance id>;<id in component>"), and
descendant boxes are compared relative to the instance's top-left corner, so
moving a whole instance shows up only in its own box. Nothing is lost: the
reference plus the diff rebuild the node.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from figma_fit.models import State
from figma_fit.passes.base import CHILDREN, count_nodes
from figma_fit.tokens import serialize

_BOX = "absoluteBoundingBox"


class CollapseInstances:
    name = "collapse_instances"

    def __call__(self, state: State) -> tuple[State, str]:
        collapsed: dict[str, int] = defaultdict(int)  # instance name -> count
        removed_nodes = 0

        def visit(node: dict[str, Any]) -> dict[str, Any]:
            nonlocal removed_nodes
            children = node.get(CHILDREN)
            if not children:
                return node
            # Bottom-up, so a diff always points into the reference as it is emitted.
            first_of: dict[str, dict[str, Any]] = {}
            new_children = []
            for child in map(visit, children):
                key = _group_key(child)
                ref = first_of.get(key) if key else None
                if ref is None:
                    if key:
                        first_of[key] = child
                    new_children.append(child)
                    continue
                short = _collapse(child, ref)
                if short is None:
                    new_children.append(child)
                else:
                    collapsed[child.get("name", "?")] += 1
                    removed_nodes += count_nodes(child) - 1
                    new_children.append(short)
            return {**node, CHILDREN: new_children}

        roots = [visit(root) for root in state.data]
        if not collapsed:
            return state, ""
        legend = dict(state.legend)
        conventions = dict(legend.get("conventions", {}))
        conventions["sameAs"] = (
            "node equals the node with id sameAs, except for its own box and the values in diff "
            "(JSON pointers; descendant boxes relative to the instance; descendant ids omitted)"
        )
        legend["conventions"] = conventions
        summary = ", ".join(f"{name}×{n + 1}" for name, n in collapsed.items())
        return State(roots, legend), f"{summary} (−{removed_nodes} nodes)"


def _group_key(node: dict[str, Any]) -> str | None:
    if node.get("type") != "INSTANCE" or "componentId" not in node:
        return None
    box = node.get(_BOX) or {}
    return serialize(
        [node["componentId"], node.get("componentProperties"), box.get("width"), box.get("height")]
    )


def _collapse(node: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any] | None:
    flat_node = _flatten(_normalize(node))
    flat_ref = _flatten(_normalize(ref))
    if flat_node.keys() != flat_ref.keys():
        return None  # different shape: an override added or removed layers
    diff = {path: value for path, value in flat_node.items() if flat_ref[path] != value}
    short: dict[str, Any] = {"id": node.get("id"), "name": node.get("name"), "type": "INSTANCE"}
    short["sameAs"] = ref.get("id")
    if _BOX in node:
        short[_BOX] = node[_BOX]
    if diff:
        short["diff"] = diff
    if len(serialize(short)) >= len(serialize(node)):
        return None
    return short


def _normalize(instance: dict[str, Any]) -> dict[str, Any]:
    """Drop ids and the instance's own position; make descendant boxes relative."""
    box = instance.get(_BOX) or {}
    ox, oy = box.get("x", 0), box.get("y", 0)

    def norm(node: dict[str, Any], top: bool) -> dict[str, Any]:
        out = {k: v for k, v in node.items() if k not in ("id", CHILDREN)}
        if top:
            out.pop(_BOX, None)
            out.pop("absoluteRenderBounds", None)
        else:
            for key in (_BOX, "absoluteRenderBounds"):
                b = node.get(key)
                if isinstance(b, dict) and "x" in b and "y" in b:
                    out[key] = {**b, "x": b["x"] - ox, "y": b["y"] - oy}
        if CHILDREN in node:
            out[CHILDREN] = [norm(c, False) for c in node[CHILDREN]]
        return out

    return norm(instance, True)


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    """Map every leaf (and every empty container) to its JSON pointer.

    Colours and boxes are leaves: minify rewrites them as a whole (hex string,
    [x, y, w, h]), so a pointer into one of their fields would go stale.
    """
    if isinstance(value, dict) and value and not _is_atomic(value):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{path}/{_escape(str(k))}"))
        return out
    if isinstance(value, list) and value:
        out = {}
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{path}/{i}"))
        return out
    return {path: value}


def _is_atomic(value: dict[str, Any]) -> bool:
    keys = value.keys()
    return keys in ({"r", "g", "b"}, {"r", "g", "b", "a"}, {"x", "y", "width", "height"})


def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")
