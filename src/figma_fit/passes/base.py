"""The Pass protocol and small tree helpers the passes share."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from figma_fit.models import State

CHILDREN = "children"


class Pass(Protocol):
    """A pure transform: returns a NEW state plus a short human note.

    The note says what was removed or rewritten ("" when nothing changed).
    Running a pass on its own output must change nothing.
    """

    name: str

    def __call__(self, state: State) -> tuple[State, str]: ...


def walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Pre-order traversal of a node and its descendants."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.get(CHILDREN) or ()))


def count_nodes(node: dict[str, Any]) -> int:
    return sum(1 for _ in walk(node))


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
