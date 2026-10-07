"""Deterministic synthetic Figma trees, sized from tiny to huge.

They contain what the passes look for: hidden layers, off-canvas layers,
wrapper groups, repeated paints, repeated component instances with text
overrides, long text, and unrounded floats.
"""

from __future__ import annotations

import random
from typing import Any


def color(rng: random.Random, palette: list[dict[str, float]]) -> dict[str, float]:
    return dict(rng.choice(palette))


def make_frame(seed: int, sections: int, rows: int, long_text: int = 0) -> dict[str, Any]:
    rng = random.Random(seed)
    palette = [{"r": rng.random(), "g": rng.random(), "b": rng.random(), "a": 1} for _ in range(5)]
    counter = [100]

    def nid() -> str:
        counter[0] += 1
        return f"{seed}:{counter[0]}"

    def paint() -> list[dict[str, Any]]:
        return [{"blendMode": "NORMAL", "type": "SOLID", "color": color(rng, palette)}]

    def text(x: float, y: float, chars: str, node_id: str | None = None) -> dict[str, Any]:
        return {
            "id": node_id or nid(),
            "name": "Label",
            "type": "TEXT",
            "visible": True,
            "blendMode": "PASS_THROUGH",
            "characters": chars,
            "absoluteBoundingBox": {"x": x, "y": y, "width": 200.0, "height": 24.000001},
            "absoluteRenderBounds": {"x": x, "y": y, "width": 199.5, "height": 22.7},
            "style": {
                "fontFamily": "Inter",
                "fontWeight": 400,
                "fontSize": 16,
                "lineHeightPx": 24.0000002,
            },
            "fills": paint(),
            "constraints": {"vertical": "TOP", "horizontal": "LEFT"},
            "effects": [],
        }

    def row(x: float, y: float, i: int) -> dict[str, Any]:
        inst_id = nid()
        return {
            "id": inst_id,
            "name": "Row",
            "type": "INSTANCE",
            "componentId": "9:1",
            "componentProperties": {"State": {"type": "VARIANT", "value": "Default"}},
            "absoluteBoundingBox": {"x": x, "y": y, "width": 600, "height": 48},
            "fills": [{"blendMode": "NORMAL", "type": "SOLID", "color": dict(palette[0])}],
            "children": [
                text(x + 16, y + 12, f"Item {i}", f"I{inst_id};9:2"),
                text(x + 400, y + 12, f"${i * 3}.00", f"I{inst_id};9:3"),
            ],
        }

    def section(idx: int, y: float) -> dict[str, Any]:
        children: list[dict[str, Any]] = [
            {  # wrapper group around a title
                "id": nid(),
                "name": "Title wrap",
                "type": "GROUP",
                "absoluteBoundingBox": {"x": 40, "y": y, "width": 200, "height": 24},
                "children": [text(40, y, f"Section {idx}")],
            },
            {  # hidden layer with content
                "id": nid(),
                "name": "Old",
                "type": "FRAME",
                "visible": False,
                "absoluteBoundingBox": {"x": 40, "y": y, "width": 600, "height": 400},
                "children": [text(40, y, "stale") for _ in range(3)],
            },
            {  # off-canvas layer
                "id": nid(),
                "name": "Parked",
                "type": "RECTANGLE",
                "absoluteBoundingBox": {"x": 99999, "y": 0, "width": 10, "height": 10},
                "fills": paint(),
            },
        ]
        for r in range(rows):
            children.append(row(40, y + 40 + r * 56, r))
        if long_text:
            words = ["lorem", "ipsum", "dolor", "sit", "amet"]
            body = " ".join(rng.choice(words) for _ in range(long_text))
            children.append(text(40, y + 40 + rows * 56, body))
        return {
            "id": nid(),
            "name": f"Section {idx}",
            "type": "FRAME",
            "visible": True,
            "opacity": 1,
            "blendMode": "PASS_THROUGH",
            "clipsContent": False,
            "layoutMode": "VERTICAL",
            "itemSpacing": 8,
            "absoluteBoundingBox": {"x": 0, "y": y, "width": 1440, "height": 60 + rows * 56},
            "fills": paint(),
            "strokes": [],
            "effects": [{"type": "DROP_SHADOW", "visible": False, "radius": 4}],
            "children": children,
        }

    sections_list = []
    y = 0.0
    for s in range(sections):
        sec = section(s, y)
        sections_list.append(sec)
        y += sec["absoluteBoundingBox"]["height"] + 24

    return {
        "id": f"{seed}:1",
        "name": "Screen",
        "type": "FRAME",
        "clipsContent": True,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": max(y, 900)},
        "fills": paint(),
        "children": sections_list,
    }


def index(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every node by id."""
    out = {}
    stack = [node]
    while stack:
        n = stack.pop()
        out[n["id"]] = n
        stack.extend(n.get("children") or ())
    return out
