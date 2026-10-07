"""Figma rules for the generic minify pass."""

from __future__ import annotations

from typing import Any

from figma_fit.passes.generic_minify import Minify, MinifyRules

# Values the Figma REST API reports that equal what a renderer assumes anyway.
_DEFAULTS: dict[str, tuple[Any, ...]] = {
    "visible": (True,),
    "opacity": (1,),
    "blendMode": ("PASS_THROUGH",),
    "locked": (False,),
    "isMask": (False,),
    "rotation": (0,),
    "scrollBehavior": ("SCROLLS",),
    "layoutAlign": ("INHERIT",),
    "layoutGrow": (0,),
    "layoutPositioning": ("AUTO",),
    "clipsContent": (False,),
    "constraints": ({"vertical": "TOP", "horizontal": "LEFT"},),
    "letterSpacing": (0,),
    "paragraphSpacing": (0,),
    "paragraphIndent": (0,),
    "lineIndentations": ([0],),
    "lineTypes": (["NONE"],),
    "preserveRatio": (False,),
    "layoutWrap": ("NO_WRAP",),
}

# absoluteRenderBounds repeats absoluteBoundingBox except for effect overflow;
# plugin data is not rendering.
_DROP = frozenset({"absoluteRenderBounds", "pluginData", "sharedPluginData"})

_RENAMES = {
    "absoluteBoundingBox": "box",
    "characters": "text",
    "componentId": "cid",
    "componentProperties": "props",
    "layoutMode": "layout",
    "itemSpacing": "gap",
    "counterAxisSpacing": "gap2",
    "paddingTop": "pt",
    "paddingRight": "pr",
    "paddingBottom": "pb",
    "paddingLeft": "pl",
    "primaryAxisAlignItems": "mainAlign",
    "counterAxisAlignItems": "crossAlign",
    "primaryAxisSizingMode": "mainSizing",
    "counterAxisSizingMode": "crossSizing",
    "layoutSizingHorizontal": "sizeH",
    "layoutSizingVertical": "sizeV",
    "cornerRadius": "radius",
    "rectangleCornerRadii": "radii",
    "strokeWeight": "strokeW",
    "individualStrokeWeights": "strokeWs",
    "clipsContent": "clip",
    "characterStyleOverrides": "charStyles",
    "styleOverrideTable": "styleTable",
}

_RENAME_NOTES = {"absoluteBoundingBox": " as [x, y, width, height]"}


def _is_default(container: Any, key: str, value: Any) -> bool:
    # NORMAL is the default blend for paints and effects (no "id"), but on a node it
    # differs from the PASS_THROUGH default by isolating the layer, so keep it there.
    return key == "blendMode" and value == "NORMAL" and "id" not in container


def _hex_color(key: str, value: Any) -> str | None:
    if not isinstance(value, dict) or value.keys() not in ({"r", "g", "b"}, {"r", "g", "b", "a"}):
        return None
    try:
        channels = [value["r"], value["g"], value["b"]]
        alpha = value.get("a", 1)
        hex_ = "".join(f"{round(float(c) * 255):02x}" for c in channels)
        if alpha != 1:
            hex_ += f"{round(float(alpha) * 255):02x}"
    except (TypeError, ValueError):
        return None
    return "#" + hex_


def _box_list(key: str, value: Any) -> list[float] | None:
    if key != "absoluteBoundingBox" or not isinstance(value, dict):
        return None
    if value.keys() != {"x", "y", "width", "height"}:
        return None
    return [_num(value[k]) for k in ("x", "y", "width", "height")]


def _num(v: Any) -> Any:
    if isinstance(v, float):
        r = round(v, 2)
        return int(r) if r.is_integer() else r
    return v


FIGMA_MINIFY_RULES = MinifyRules(
    defaults=_DEFAULTS,
    drop_keys=_DROP,
    is_default=_is_default,
    renames=_RENAMES,
    rename_notes=_RENAME_NOTES,
    rewrites=(_hex_color, _box_list),
    pointer_maps=frozenset({"diff"}),
)


def figma_minify() -> Minify:
    return Minify(FIGMA_MINIFY_RULES)
