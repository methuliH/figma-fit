"""Turn fetched Figma nodes into a response that fits the budget.

Pure: takes what figma.py fetched, returns the exact text a tool sends back.
The guarantee lives here: every returned text is estimated at or under the
effective limit, which is under the budget.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from figma_fit.figma import FetchedNode
from figma_fit.models import (
    FitResult,
    ParentShell,
    PassNote,
    SplitGroup,
    SplitItem,
    SplitPlan,
    State,
)
from figma_fit.passes import DEFAULT_PASSES, LOCAL_PASSES, Pass
from figma_fit.pipeline import SAFETY, apply_all, compact, effective_limit
from figma_fit.report import fmt_tokens, report_line, with_own_count
from figma_fit.split import plan_split
from figma_fit.tokens import DEFAULT_ESTIMATOR, Estimator, serialize

MIN_BUDGET = 1000
FOLLOW_UP_TOOL = "fetch_node_within_budget"
_NAME_CHARS = 60
_ENVELOPE_MARGIN = 32
IN_NOTE = "id of the parent frame the node sits in; its own layout is listed under parents"


class BudgetError(ValueError):
    pass


def fit_nodes(
    fetched: Sequence[FetchedNode],
    budget: int,
    *,
    passes: Sequence[Pass] = DEFAULT_PASSES,
    plan_offset: int = 0,
    estimator: Estimator = DEFAULT_ESTIMATOR,
) -> FitResult:
    if budget < MIN_BUDGET:
        raise BudgetError(f"budget must be at least {MIN_BUDGET} tokens (got {budget})")
    if not fetched:
        raise ValueError("no nodes to fit")

    head = fetched[0]
    file_info = {"key": head.file_key, "name": head.file_name, "version": head.version}
    roots = [f.document for f in fetched]
    original = estimator.count(serialize(roots))
    limit = effective_limit(budget)

    def render_fit(state: State, notes: Sequence[PassNote]) -> str:
        return _render_fit(state, notes, file_info, budget, original, estimator)[0]

    result = compact(roots, passes, render_fit, limit, estimator=estimator)
    if result.fits:
        return FitResult(
            status="fit",
            text=result.text,
            tokens=result.tokens,
            budget=budget,
            original_tokens=original,
            notes=result.notes,
            state=result.state,
        )

    # Size nodes as a follow-up call would see them at worst: only the passes whose
    # effect on a node does not depend on the rest of the tree.
    local_passes = [p for p in passes if p in LOCAL_PASSES]
    local = apply_all(roots, local_passes)
    envelope = _envelope(local.legend, result.notes, file_info, budget, original, estimator)
    plan = plan_split(local.data, limit, envelope, estimator=estimator)
    keys = local.legend.get("keys", {})
    text, tokens = _render_split(
        plan,
        plan_offset,
        file_info,
        budget,
        original,
        result.notes,
        limit,
        envelope,
        keys,
        estimator,
    )
    return FitResult(
        status="split",
        text=text,
        tokens=tokens,
        budget=budget,
        original_tokens=original,
        notes=result.notes,
        plan=plan,
    )


def _render_fit(
    state: State,
    notes: Sequence[PassNote],
    file_info: dict[str, str],
    budget: int,
    original: int,
    estimator: Estimator,
) -> tuple[str, int]:
    body: dict[str, Any] = {"status": "fit", "file": file_info}
    if state.legend:
        body["legend"] = state.legend
    body["data"] = state.data
    body["passes"] = [[n.pass_name, n.removed, n.tokens_before, n.tokens_after] for n in notes]
    json_text = serialize(body)

    def build(tokens: int) -> str:
        line = report_line(
            status="fit", tokens=tokens, budget=budget, original=original, notes=notes
        )
        return line + "\n" + json_text

    return with_own_count(build, estimator)


def _envelope(
    legend: dict[str, Any],
    notes: Sequence[PassNote],
    file_info: dict[str, str],
    budget: int,
    original: int,
    estimator: Estimator,
) -> int:
    """Upper bound on a follow-up response's tokens that are not node data."""
    worst_legend = dict(legend)
    worst_legend["conventions"] = {
        "@name": "value is legend.styles[name]",
        "sameAs": "x" * 220,  # length of the real explanation, with room to spare
    }
    _, tokens = _render_fit(State([], worst_legend), notes, file_info, budget, original, estimator)
    return tokens + _ENVELOPE_MARGIN


def _render_split(
    plan: SplitPlan,
    offset: int,
    file_info: dict[str, str],
    budget: int,
    original: int,
    notes: Sequence[PassNote],
    limit: int,
    envelope: int,
    keys: dict[str, str],
    estimator: Estimator,
) -> tuple[str, int]:
    groups = list(plan.groups[offset:])
    oversize = list(plan.oversize)

    def build_body(n_groups: int, n_oversize: int, with_parents: bool) -> str:
        shown = groups[:n_groups]
        body: dict[str, Any] = {
            "status": "split",
            "file": file_info,
            "reason": (
                f"~{fmt_tokens(original)} tokens of data; even after all passes it does not "
                f"fit {fmt_tokens(budget)}. Fetch it in the calls below."
            ),
            "next": (
                f'Call {FOLLOW_UP_TOOL}(file_key="{file_info["key"]}", node_ids=<call.node_ids>, '
                f"budget={budget}) for each call. Follow-ups are served from cache."
            ),
        }
        if plan.parents:
            legend: dict[str, Any] = {"conventions": {"in": IN_NOTE}}
            body["legend"] = legend
            if with_parents:
                listed = [it for g in shown for it in g.items] + oversize[:n_oversize]
                shells = [_shell(p) for p in plan.ancestors(listed)]
                if shells:
                    used = _keys_used(shells, keys)
                    if used:
                        legend["keys"] = used
                    body["parents"] = shells
            else:
                body["parents_omitted"] = "parent layout does not fit this budget"
        body["calls"] = [_call(g) for g in shown]
        if oversize[:n_oversize]:
            body["oversize"] = [_oversize(it, envelope) for it in oversize[:n_oversize]]
        remaining = len(groups) - n_groups
        if remaining:
            body["more"] = {
                "remaining_calls": remaining,
                "how": f"repeat this request with plan_offset={offset + n_groups}",
            }
        if len(oversize) > n_oversize:
            body["more_oversize"] = len(oversize) - n_oversize
        return serialize(body)

    def render(n_groups: int, n_oversize: int, with_parents: bool) -> tuple[str, int]:
        json_text = build_body(n_groups, n_oversize, with_parents)

        def build(tokens: int) -> str:
            line = report_line(
                status="split", tokens=tokens, budget=budget, original=original, notes=notes
            )
            return line + "\n" + json_text

        return with_own_count(build, estimator)

    def fits(n_groups: int, n_oversize: int, with_parents: bool) -> bool:
        return render(n_groups, n_oversize, with_parents)[1] <= limit

    # Keep as many calls as fit (with their parents' layout if possible), then as many
    # oversize notes as fit.
    with_parents = True
    n_groups = _largest_fitting(len(groups), lambda n: fits(n, 0, True))
    if groups and n_groups == 0:
        with_parents = False
        n_groups = _largest_fitting(len(groups), lambda n: fits(n, 0, False))
    n_over = _largest_fitting(len(oversize), lambda n: fits(n_groups, n, with_parents))
    text, tokens = render(n_groups, n_over, with_parents)
    if tokens > limit or (groups and n_groups == 0):
        # Not even one call fits next to the envelope; paging would never advance.
        text = (
            f"figma-fit: SPLIT, plan too large to show at budget {budget}. "
            f"Retry with a larger budget or a smaller frame."
        )
        tokens = estimator.count(text)
    return text, tokens


def _largest_fitting(n_max: int, fits: Any) -> int:
    """Largest n in [0, n_max] with fits(n), assuming fits is monotone (binary search)."""
    lo, hi = 0, n_max
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _call(group: SplitGroup) -> dict[str, Any]:
    call: dict[str, Any] = {
        "node_ids": group.node_ids,
        "est_tokens": group.est_tokens,
        "layers": [f"{_short(it.name)} ({it.type})" for it in group.items],
    }
    parent_ids = [it.parent_id for it in group.items]
    if len(set(parent_ids)) == 1:
        if parent_ids[0] is not None:
            call["in"] = parent_ids[0]
    else:
        call["in"] = parent_ids  # one per node id
    return call


def _oversize(it: SplitItem, envelope: int) -> dict[str, Any]:
    needed = math.ceil((it.est_tokens + envelope) / SAFETY)
    out: dict[str, Any] = {
        "node_id": it.node_id,
        "layer": f"{_short(it.name)} ({it.type})",
        "est_tokens": it.est_tokens,
        "hint": f"too large on its own; needs a budget of about {fmt_tokens(needed)}+",
    }
    if it.parent_id is not None:
        out["in"] = it.parent_id
    return out


def _shell(parent: ParentShell) -> dict[str, Any]:
    shell = dict(parent.shell)
    if parent.parent_id is not None:
        shell["in"] = parent.parent_id
    return shell


def _keys_used(shells: list[dict[str, Any]], keys: dict[str, str]) -> dict[str, str]:
    """The legend.keys entries needed to read these shells."""
    seen: set[str] = set()
    stack: list[Any] = list(shells)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            seen.update(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return {short: long for short, long in keys.items() if short in seen}


def _short(name: str) -> str:
    return name if len(name) <= _NAME_CHARS else name[: _NAME_CHARS - 1] + "…"
