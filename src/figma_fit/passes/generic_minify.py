"""Rule-driven minification for any JSON tree.

Drops default and empty values, rounds floats, applies value rewrites and
shortens keys, recording every renamed key in ``legend.keys``. The rules make
it Figma-specific (see ``figma_minify.py``); the mechanism is not.

Rounding is slightly lossy, and the note says so.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from figma_fit.models import State
from figma_fit.passes.base import plural

# (key, value) -> new value, or None to leave the value alone.
Rewrite = Callable[[str, Any], Any]


@dataclass(frozen=True)
class MinifyRules:
    defaults: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)  # dropped when equal
    # Context-dependent defaults: (containing object, key, value) -> drop?
    is_default: Callable[[Mapping[str, Any], str, Any], bool] | None = None
    drop_keys: frozenset[str] = frozenset()  # always dropped
    keep_empty: frozenset[str] = frozenset()  # empty values kept for these keys
    renames: Mapping[str, str] = field(default_factory=dict)
    rename_notes: Mapping[str, str] = field(default_factory=dict)  # extra legend text per key
    rewrites: tuple[Rewrite, ...] = ()
    pointer_maps: frozenset[str] = frozenset()  # dict keys that are JSON pointers ("diff")
    decimals: int = 2


class Minify:
    name = "minify"

    def __init__(self, rules: MinifyRules) -> None:
        self.rules = rules

    def __call__(self, state: State) -> tuple[State, str]:
        stats = {"defaults": 0, "dropped": 0, "rounded": 0, "rewritten": 0}
        used: set[str] = set()
        rules = self.rules

        def value(key: str, v: Any) -> Any:
            for rewrite in rules.rewrites:
                new = rewrite(key, v)
                if new is not None:
                    if new != v:
                        stats["rewritten"] += 1
                    return new
            if isinstance(v, float):
                r = round(v, rules.decimals)
                r = int(r) if r.is_integer() else r
                if r != v:
                    stats["rounded"] += 1
                return r
            if isinstance(v, dict):
                return obj(v)
            if isinstance(v, list):
                return [value(key, item) for item in v]
            return v

        def obj(d: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k, v in d.items():
                if k in rules.drop_keys:
                    stats["dropped"] += 1
                    continue
                if (k in rules.defaults and v in rules.defaults[k]) or (
                    rules.is_default and rules.is_default(d, k, v)
                ):
                    stats["defaults"] += 1
                    continue
                if k in rules.pointer_maps and isinstance(v, dict):
                    new_v: Any = pointers(v)
                else:
                    new_v = value(k, v)
                if new_v in ([], {}) and k not in rules.keep_empty and k not in rules.pointer_maps:
                    stats["defaults"] += 1
                    continue
                short = rules.renames.get(k, k)
                if short != k:
                    used.add(k)
                out[short] = new_v
            return out

        def pointers(d: dict[str, Any]) -> dict[str, Any]:
            # Keys are paths into another node: rename their segments, keep every entry
            # (a default or empty value here is a real difference from the reference).
            out = {}
            for path, v in d.items():
                segments = path.split("/")
                if any(s in rules.drop_keys for s in segments):
                    stats["dropped"] += 1
                    continue
                for s in segments:
                    if s in rules.renames:
                        used.add(s)
                new_path = "/".join(rules.renames.get(s, s) for s in segments)
                last = segments[-1] if segments else ""
                out[new_path] = value(last, v)
            return out

        roots = [obj(root) for root in state.data]
        legend = dict(state.legend)
        if "styles" in legend:
            legend["styles"] = {name: value(name, v) for name, v in legend["styles"].items()}
        keys = dict(legend.get("keys", {}))
        for long in sorted(used):
            short = rules.renames[long]
            keys[short] = long + rules.rename_notes.get(long, "")
        if keys:
            legend["keys"] = keys
        return State(roots, legend), _note(stats)


def _note(stats: dict[str, int]) -> str:
    labels = {
        "defaults": ("default/empty value", ""),
        "dropped": ("redundant field", ""),
        "rewritten": ("value", " rewritten"),
        "rounded": ("float", " rounded (lossy)"),
    }
    return ", ".join(
        plural(stats[k], noun) + suffix for k, (noun, suffix) in labels.items() if stats[k]
    )
