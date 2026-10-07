"""Move repeated paints, effects and text styles into the legend.

A value used two or more times becomes ``legend.styles["p1"]`` and each node
refers to it as ``"@p1"``. A value only moves when that makes the output
smaller, so the pass never grows the payload.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from figma_fit.models import State
from figma_fit.passes.base import CHILDREN, walk
from figma_fit.tokens import serialize

# fills and strokes share one namespace: the same paint is often both.
_PREFIX = {"fills": "p", "strokes": "p", "effects": "fx", "style": "t"}
_LABEL = {"p": "paints", "fx": "effects", "t": "text styles"}
REF_MARK = "@"


class DedupeStyles:
    name = "dedupe_styles"

    def __call__(self, state: State) -> tuple[State, str]:
        uses: Counter[tuple[str, str]] = Counter()
        values: dict[tuple[str, str], Any] = {}
        for root in state.data:
            for node in walk(root):
                for key, prefix in _PREFIX.items():
                    value = node.get(key)
                    if _dedupable(value):
                        k = (prefix, serialize(value))
                        uses[k] += 1
                        values[k] = value

        styles = dict(state.legend.get("styles", {}))
        next_n = Counter(_prefix_of(name) for name in styles)
        refs: dict[tuple[str, str], str] = {}
        for k, n in uses.most_common():
            prefix, text = k
            if n < 2:
                break
            name = f"{prefix}{next_n[prefix] + 1}"
            ref = serialize(REF_MARK + name)
            # inline: n copies. moved: one legend entry ("name":value,) plus n refs.
            if n * len(text) <= len(text) + len(name) + 4 + n * len(ref):
                continue
            next_n[prefix] += 1
            styles[name] = values[k]
            refs[k] = REF_MARK + name

        if not refs:
            return state, ""

        def visit(node: dict[str, Any]) -> dict[str, Any]:
            out = dict(node)
            for key, prefix in _PREFIX.items():
                value = node.get(key)
                if _dedupable(value):
                    ref = refs.get((prefix, serialize(value)))
                    if ref:
                        out[key] = ref
            if node.get(CHILDREN):
                out[CHILDREN] = [visit(c) for c in node[CHILDREN]]
            return out

        roots = [visit(root) for root in state.data]
        legend = {**state.legend, "styles": styles}
        conventions = dict(legend.get("conventions", {}))
        conventions["@name"] = "value is legend.styles[name]"
        legend["conventions"] = conventions
        return State(roots, legend), _note(refs, uses)


def _dedupable(value: Any) -> bool:
    return isinstance(value, dict | list) and bool(value)


def _prefix_of(name: str) -> str:
    return name.rstrip("0123456789")


def _note(refs: dict[tuple[str, str], str], uses: Counter[tuple[str, str]]) -> str:
    parts = []
    for prefix, label in _LABEL.items():
        moved = [k for k in refs if k[0] == prefix]
        if moved:
            total = sum(uses[k] for k in moved)
            parts.append(f"{total} {label}→{len(moved)}")
    return ", ".join(parts)
