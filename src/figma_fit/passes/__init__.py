"""Compaction passes, cheapest and most information-preserving first."""

from __future__ import annotations

from figma_fit.passes.base import Pass
from figma_fit.passes.figma_flatten import FlattenWrappers
from figma_fit.passes.figma_instances import CollapseInstances
from figma_fit.passes.figma_invisible import DropInvisible
from figma_fit.passes.figma_minify import figma_minify
from figma_fit.passes.figma_styles import DedupeStyles

DEFAULT_PASSES: tuple[Pass, ...] = (
    DropInvisible(),
    FlattenWrappers(),
    DedupeStyles(),
    CollapseInstances(),
    figma_minify(),
)

PASS_NAMES = tuple(p.name for p in DEFAULT_PASSES)

# Passes whose result for a node does not depend on the rest of the tree. The
# split planner sizes nodes with these, so a follow-up call (which may also
# dedupe and collapse) comes out no larger than planned.
LOCAL_PASSES: tuple[Pass, ...] = tuple(
    p for p in DEFAULT_PASSES if p.name in ("drop_invisible", "flatten_wrappers", "minify")
)


def select_passes(names: list[str] | None) -> tuple[Pass, ...]:
    """The default passes, or the named subset (always in the default order)."""
    if names is None:
        return DEFAULT_PASSES
    unknown = set(names) - set(PASS_NAMES)
    if unknown:
        raise ValueError(f"unknown pass(es) {sorted(unknown)}; choose from {list(PASS_NAMES)}")
    return tuple(p for p in DEFAULT_PASSES if p.name in names)


__all__ = ["DEFAULT_PASSES", "LOCAL_PASSES", "PASS_NAMES", "Pass", "select_passes"]
