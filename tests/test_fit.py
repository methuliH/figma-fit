"""The product claim: a response is never estimated over the budget."""

import json

import pytest
import synth
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from figma_fit.figma import FetchedNode
from figma_fit.fit import MIN_BUDGET, BudgetError, fit_nodes
from figma_fit.passes import select_passes
from figma_fit.tokens import estimate


def fetched(doc, file_key="K"):
    return FetchedNode(file_key, doc["id"], "File", "42", "", doc, {}, {}, {})


# Generated once: hypothesis varies budgets and picks among these.
FRAMES = {
    "small": synth.make_frame(1, sections=2, rows=3),
    "medium": synth.make_frame(2, sections=6, rows=12),
    "large": synth.make_frame(3, sections=20, rows=25, long_text=60),
    "long_text": synth.make_frame(4, sections=4, rows=2, long_text=3000),
}
INDEX = {name: synth.index(doc) for name, doc in FRAMES.items()}


def check_follow_ups(name, result, budget):
    """Every planned call, made as a follow-up, also stays within the budget."""
    for group in result.plan.groups:
        nodes = [fetched(INDEX[name][i]) for i in group.node_ids]
        follow = fit_nodes(nodes, budget)
        assert follow.tokens <= budget
        assert estimate(follow.text) == follow.tokens
        assert follow.status == "fit", (name, budget, group)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=st.sampled_from(sorted(FRAMES)), budget=st.integers(MIN_BUDGET, 50_000))
def test_output_never_exceeds_budget(name, budget):
    result = fit_nodes([fetched(FRAMES[name])], budget)
    assert result.tokens <= budget
    assert estimate(result.text) == result.tokens
    if result.status == "split":
        assert all(g.est_tokens <= budget for g in result.plan.groups)


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=st.sampled_from(["medium", "large"]), budget=st.integers(MIN_BUDGET, 20_000))
def test_split_plan_follow_ups_fit(name, budget):
    result = fit_nodes([fetched(FRAMES[name])], budget)
    if result.status == "split":
        check_follow_ups(name, result, budget)


def test_fit_response_shape():
    result = fit_nodes([fetched(FRAMES["medium"])], 20_000)
    assert result.status == "fit"
    line, body = result.text.split("\n", 1)
    assert line.startswith("figma-fit: ")
    assert "saved" in line and "collapse_instances Row×" in line
    data = json.loads(body)
    assert data["status"] == "fit"
    assert data["file"] == {"key": "K", "name": "File", "version": "42"}
    assert data["data"][0]["id"] == FRAMES["medium"]["id"]
    assert set(data["legend"]) >= {"styles", "conventions"}  # stopped before minify
    assert [p[0] for p in data["passes"]] == [n.pass_name for n in result.notes]


def test_stops_early_and_keeps_full_detail_when_budget_allows():
    result = fit_nodes([fetched(FRAMES["small"])], 50_000)
    assert result.status == "fit"
    assert result.notes == ()
    assert json.loads(result.text.split("\n", 1)[1])["data"] == [FRAMES["small"]]


def test_split_response_lists_calls_and_how_to_make_them():
    result = fit_nodes([fetched(FRAMES["large"])], 8_000)
    assert result.status == "split"
    body = json.loads(result.text.split("\n", 1)[1])
    assert body["calls"] and all(c["node_ids"] for c in body["calls"])
    assert 'fetch_node_within_budget(file_key="K"' in body["next"]


def test_long_split_plan_is_paged():
    first = fit_nodes([fetched(FRAMES["large"])], MIN_BUDGET)
    body = json.loads(first.text.split("\n", 1)[1])
    shown = len(body["calls"])
    assert body["more"]["remaining_calls"] == len(first.plan.groups) - shown
    second = fit_nodes([fetched(FRAMES["large"])], MIN_BUDGET, plan_offset=shown)
    next_ids = json.loads(second.text.split("\n", 1)[1])["calls"][0]["node_ids"]
    assert next_ids == first.plan.groups[shown].node_ids


def test_oversize_text_is_reported_not_returned():
    result = fit_nodes([fetched(FRAMES["long_text"])], 4_000)
    assert result.status == "split"
    assert result.plan.oversize
    body = json.loads(result.text.split("\n", 1)[1])
    assert body["oversize"][0]["hint"].startswith("too large on its own")


def test_selected_passes_only():
    result = fit_nodes([fetched(FRAMES["medium"])], 20_000, passes=select_passes(["minify"]))
    assert [n.pass_name for n in result.notes] in ([], ["minify"])


def test_budget_below_minimum_is_rejected():
    with pytest.raises(BudgetError):
        fit_nodes([fetched(FRAMES["small"])], MIN_BUDGET - 1)
