"""Run passes in order until the rendered output fits the budget.

Knows nothing about Figma: the data is opaque, passes transform it, and the
caller's ``render`` turns it into the exact string the tool will return.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from figma_fit.models import PassNote, State
from figma_fit.passes.base import Pass
from figma_fit.tokens import DEFAULT_ESTIMATOR, Estimator, serialize

# Estimates are bytes / 3.2. Until calibrated (PLAN.md, M5), aim 20% under the
# budget so an estimate that runs low still lands within it.
SAFETY = 0.80

Render = Callable[[State, Sequence[PassNote]], str]


def effective_limit(budget: int, safety: float = SAFETY) -> int:
    return math.floor(budget * safety)


def payload_tokens(state: State, estimator: Estimator = DEFAULT_ESTIMATOR) -> int:
    """Size of what the passes control: the data and its legend."""
    return estimator.count(serialize({"legend": state.legend, "data": state.data}))


@dataclass(frozen=True)
class Compacted:
    state: State
    notes: tuple[PassNote, ...]
    text: str
    tokens: int
    fits: bool


def compact(
    data: Any,
    passes: Sequence[Pass],
    render: Render,
    limit: int,
    *,
    estimator: Estimator = DEFAULT_ESTIMATOR,
) -> Compacted:
    """Apply passes one at a time, stopping as soon as the output fits ``limit``.

    Cheap, information-preserving passes come first, so stopping early keeps
    the most information.
    """
    state = State(data)
    notes: list[PassNote] = []
    text = render(state, notes)
    tokens = estimator.count(text)
    for p in passes:
        if tokens <= limit:
            break
        before = payload_tokens(state, estimator)
        new_state, removed = p(state)
        if removed:
            notes.append(PassNote(p.name, removed, before, payload_tokens(new_state, estimator)))
        state = new_state
        text = render(state, notes)
        tokens = estimator.count(text)
    return Compacted(state, tuple(notes), text, tokens, tokens <= limit)


def apply_all(data: Any, passes: Sequence[Pass]) -> State:
    """Every pass, unconditionally (used to size nodes for a split plan)."""
    state = State(data)
    for p in passes:
        state, _ = p(state)
    return state
