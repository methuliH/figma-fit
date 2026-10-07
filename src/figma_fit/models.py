"""Result types shared by the pipeline, split planner and report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class State:
    """What the passes transform: the data plus the legend that explains it.

    Passes never mutate a State; they return a new one.
    """

    data: Any
    legend: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PassNote:
    pass_name: str  # "drop_invisible"
    removed: str  # "41 hidden nodes, 3 zero-opacity nodes"
    tokens_before: int  # payload size (data + legend) before the pass
    tokens_after: int


@dataclass(frozen=True)
class SplitItem:
    node_id: str
    name: str
    type: str
    est_tokens: int


@dataclass(frozen=True)
class SplitGroup:
    """One follow-up call: these sibling-or-cousin nodes fetched together."""

    items: tuple[SplitItem, ...]
    est_tokens: int  # whole follow-up response, envelope included

    @property
    def node_ids(self) -> list[str]:
        return [item.node_id for item in self.items]


@dataclass(frozen=True)
class SplitPlan:
    groups: tuple[SplitGroup, ...]
    oversize: tuple[SplitItem, ...]  # too big on their own; never returned as data


@dataclass(frozen=True)
class FitResult:
    status: Literal["fit", "split"]
    text: str  # the exact string the tool returns
    tokens: int  # estimate of `text`; always <= budget
    budget: int
    original_tokens: int
    notes: tuple[PassNote, ...]
    state: State | None = None  # compacted data (status == "fit")
    plan: SplitPlan | None = None  # (status == "split")
