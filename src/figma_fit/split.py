"""Plan follow-up calls when a tree cannot fit in one response.

Generic: works on any tree of dicts with a children list. The caller sizes
nodes on data that has been through the subtree-local passes, and reserves
``envelope`` tokens for everything in a response that is not node data.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from figma_fit.models import ParentShell, SplitGroup, SplitItem, SplitPlan
from figma_fit.passes.base import CHILDREN
from figma_fit.tokens import DEFAULT_ESTIMATOR, Estimator, serialize

Describe = Callable[[dict[str, Any]], tuple[str, str, str]]  # node -> (id, name, type)


def default_describe(node: dict[str, Any]) -> tuple[str, str, str]:
    return str(node.get("id", "")), str(node.get("name", "")), str(node.get("type", ""))


def node_sizes(
    roots: Sequence[dict[str, Any]], estimator: Estimator = DEFAULT_ESTIMATOR
) -> dict[int, int]:
    """Estimated tokens of every node's serialized subtree, keyed by id(node).

    Computed bottom-up in one pass. Each node is counted as its own fields plus
    its children's counts plus one token per separating comma, which is never
    less than counting the whole subtree at once.
    """
    sizes: dict[int, int] = {}

    def size(node: dict[str, Any]) -> int:
        children = node.get(CHILDREN) or []
        own = estimator.count(serialize({**node, CHILDREN: []} if children else node))
        total = own + sum(size(c) for c in children) + max(len(children) - 1, 0)
        sizes[id(node)] = total
        return total

    for root in roots:
        size(root)
    return sizes


def plan_split(
    roots: Sequence[dict[str, Any]],
    limit: int,
    envelope: int,
    *,
    describe: Describe = default_describe,
    estimator: Estimator = DEFAULT_ESTIMATOR,
) -> SplitPlan:
    """Break the trees into groups that each fit ``limit`` as one response.

    Oversized nodes are replaced by their children, recursively, and their own
    fields are kept as parent shells so the layout around the children is not
    lost. A node that is too big on its own (a leaf, or a node whose own fields
    are too big) is listed as oversize and never planned as data. Small siblings
    are packed together in document order, so each call covers neighbouring
    layers.
    """
    capacity = limit - envelope
    sizes = node_sizes(roots, estimator)
    items: list[SplitItem] = []
    oversize: list[SplitItem] = []
    parents: list[ParentShell] = []

    def item(node: dict[str, Any], parent_id: str | None) -> SplitItem:
        node_id, name, type_ = describe(node)
        return SplitItem(node_id, name, type_, sizes[id(node)], parent_id)

    def collect(node: dict[str, Any], parent_id: str | None = None) -> None:
        if sizes[id(node)] <= capacity:
            items.append(item(node, parent_id))
            return
        children = node.get(CHILDREN) or []
        # The node's own fields: its total minus its children and the commas between them.
        commas = max(len(children) - 1, 0)
        shell = sizes[id(node)] - sum(sizes[id(c)] for c in children) - commas
        if not children or shell > capacity:
            oversize.append(item(node, parent_id))
            return
        node_id = describe(node)[0]
        own = {k: v for k, v in node.items() if k != CHILDREN}
        parents.append(ParentShell(node_id, parent_id, own))
        for child in children:
            collect(child, node_id)

    for root in roots:
        collect(root)

    groups: list[SplitGroup] = []
    current: list[SplitItem] = []
    used = 0
    for it in items:
        cost = it.est_tokens + (1 if current else 0)  # comma between nodes
        if current and used + cost > capacity:
            groups.append(SplitGroup(tuple(current), envelope + used))
            current, used = [], 0
            cost = it.est_tokens
        current.append(it)
        used += cost
    if current:
        groups.append(SplitGroup(tuple(current), envelope + used))

    return SplitPlan(tuple(groups), tuple(oversize), tuple(parents))
