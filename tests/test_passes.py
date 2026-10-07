import copy

import pytest
import synth

from figma_fit.models import State
from figma_fit.passes import DEFAULT_PASSES, select_passes
from figma_fit.passes.figma_flatten import FlattenWrappers
from figma_fit.passes.figma_instances import CollapseInstances
from figma_fit.passes.figma_invisible import DropInvisible
from figma_fit.passes.figma_minify import figma_minify
from figma_fit.passes.figma_styles import DedupeStyles
from figma_fit.passes.generic_minify import Minify, MinifyRules
from figma_fit.tokens import serialize


def box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def frame(id_, children=(), **props):
    return {"id": id_, "name": id_, "type": "FRAME", "children": list(children), **props}


def leaf(id_, **props):
    return {"id": id_, "name": id_, "type": "RECTANGLE", **props}


def ids(state):
    out = []
    stack = list(state.data)
    while stack:
        n = stack.pop(0)
        out.append(n["id"])
        stack[0:0] = n.get("children") or []
    return out


def run(p, *roots):
    return p(State(list(roots)))


def solid(r, g, b):
    return {"blendMode": "NORMAL", "type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": 1}}


# --- every pass ---------------------------------------------------------------


@pytest.fixture(params=["pricing", "synthetic"])
def tree(request, pricing_body):
    if request.param == "pricing":
        return pricing_body["nodes"]["12:1"]["document"]
    return synth.make_frame(3, sections=3, rows=6, long_text=20)


@pytest.mark.parametrize("p", DEFAULT_PASSES, ids=lambda p: p.name)
def test_pass_is_idempotent_and_pure(p, tree):
    original = copy.deepcopy(tree)
    once, _ = p(State([tree]))
    twice, note = p(once)
    assert tree == original  # input not mutated
    assert twice == once
    assert note == ""


@pytest.mark.parametrize("p", DEFAULT_PASSES, ids=lambda p: p.name)
def test_pass_never_grows_the_payload(p, tree):
    before = State([tree])
    after, _ = p(before)
    assert len(serialize([after.legend, after.data])) <= len(
        serialize([before.legend, before.data])
    )


def test_all_passes_shrink_the_synthetic_frame_a_lot():
    tree = synth.make_frame(3, sections=6, rows=10)
    state = State([tree])
    for p in DEFAULT_PASSES:
        state, _ = p(state)
    assert len(serialize([state.legend, state.data])) < 0.3 * len(serialize([tree]))


def test_select_passes_keeps_default_order_and_rejects_unknown():
    assert [p.name for p in select_passes(["minify", "drop_invisible"])] == [
        "drop_invisible",
        "minify",
    ]
    with pytest.raises(ValueError, match="unknown"):
        select_passes(["nope"])


# --- drop_invisible -----------------------------------------------------------


def test_drops_hidden_zero_opacity_and_off_canvas_nodes():
    root = frame(
        "1:1",
        [
            leaf("1:2", visible=False),
            leaf("1:3", opacity=0),
            leaf("1:4", absoluteBoundingBox=box(5000, 0, 10, 10)),
            frame("1:5", [leaf("1:6")], visible=False),
            leaf("1:7", absoluteBoundingBox=box(10, 10, 10, 10)),
        ],
        absoluteBoundingBox=box(0, 0, 100, 100),
    )
    state, note = run(DropInvisible(), root)
    assert ids(state) == ["1:1", "1:7"]
    assert note == "−5 nodes (2 hidden, 1 zero-opacity, 1 clipped off-canvas)"


def test_keeps_overflow_of_non_clipping_frames():
    root = frame(
        "1:1",
        [
            frame(
                "1:2",
                [leaf("1:3", absoluteBoundingBox=box(80, 0, 10, 10))],
                absoluteBoundingBox=box(0, 0, 50, 50),
            )
        ],
        absoluteBoundingBox=box(0, 0, 100, 100),
    )
    state, _ = run(DropInvisible(), root)
    assert "1:3" in ids(state)


def test_clipping_frame_drops_children_outside_it():
    root = frame(
        "1:1",
        [
            frame(
                "1:2",
                [leaf("1:3", absoluteBoundingBox=box(60, 0, 10, 10))],
                absoluteBoundingBox=box(0, 0, 50, 50),
                clipsContent=True,
            )
        ],
        absoluteBoundingBox=box(0, 0, 100, 100),
    )
    state, _ = run(DropInvisible(), root)
    assert "1:3" not in ids(state)


def test_lines_inside_the_clip_are_kept():
    root = frame(
        "1:1",
        [leaf("1:2", absoluteBoundingBox=box(0, 50, 100, 0))],
        absoluteBoundingBox=box(0, 0, 100, 100),
    )
    state, _ = run(DropInvisible(), root)
    assert "1:2" in ids(state)


def test_drops_hidden_paints_and_effects():
    root = leaf(
        "1:1",
        fills=[{**solid(1, 0, 0), "visible": False}, solid(0, 0, 1)],
        effects=[{"visible": False}],
    )
    state, note = run(DropInvisible(), root)
    assert state.data[0]["fills"] == [solid(0, 0, 1)]
    assert state.data[0]["effects"] == []
    assert note == "−2 hidden paints"


# --- flatten_wrappers ---------------------------------------------------------


def test_flattens_plain_wrappers_including_nested_ones():
    inner = leaf("1:4", absoluteBoundingBox=box(0, 0, 10, 10))
    root = frame("1:1", [{**frame("1:2", [frame("1:3", [inner])]), "type": "GROUP"}])
    state, note = run(FlattenWrappers(), root)
    assert ids(state) == ["1:1", "1:4"]
    assert note == "−2 wrappers"


@pytest.mark.parametrize(
    "props",
    [
        {"fills": [solid(1, 1, 1)]},
        {"clipsContent": True},
        {"opacity": 0.5},
        {"layoutMode": "HORIZONTAL"},
        {"effects": [{"type": "DROP_SHADOW"}]},
        {"blendMode": "MULTIPLY"},
        {"rotation": 0.3},
    ],
)
def test_keeps_wrappers_that_do_something(props):
    root = frame("1:1", [frame("1:2", [leaf("1:3")], **props)])
    state, _ = run(FlattenWrappers(), root)
    assert "1:2" in ids(state)


def test_in_auto_layout_only_same_size_wrappers_flatten():
    child = leaf("1:3", absoluteBoundingBox=box(0, 0, 10, 10))
    bigger = frame("1:2", [child], absoluteBoundingBox=box(0, 0, 50, 10))
    same = frame("1:4", [{**child, "id": "1:5"}], absoluteBoundingBox=box(0, 0, 10, 10))
    root = frame("1:1", [bigger, same], layoutMode="VERTICAL")
    state, _ = run(FlattenWrappers(), root)
    assert ids(state) == ["1:1", "1:2", "1:3", "1:5"]


def test_never_flattens_the_requested_root():
    state, _ = run(FlattenWrappers(), frame("1:1", [leaf("1:2")]))
    assert ids(state) == ["1:1", "1:2"]


# --- dedupe_styles ------------------------------------------------------------


def test_repeated_paints_move_to_the_legend():
    red = [solid(1, 0, 0)]
    root = frame("1:1", [leaf(f"1:{i}", fills=red, strokes=red) for i in range(2, 6)])
    state, note = run(DedupeStyles(), root)
    assert state.legend["styles"] == {"p1": red}
    assert all(n["fills"] == "@p1" and n["strokes"] == "@p1" for n in state.data[0]["children"])
    assert note == "8 paints→1"
    assert "@name" in state.legend["conventions"]


def test_values_used_once_stay_inline():
    root = frame("1:1", [leaf("1:2", fills=[solid(1, 0, 0)]), leaf("1:3", fills=[solid(0, 1, 0)])])
    state, note = run(DedupeStyles(), root)
    assert state == State([root]) and note == ""


# --- collapse_instances -------------------------------------------------------


def instance(id_, x, label, *, props="A", width=100):
    return {
        "id": id_,
        "name": "Row",
        "type": "INSTANCE",
        "componentId": "9:1",
        "componentProperties": {"V": {"type": "VARIANT", "value": props}},
        "absoluteBoundingBox": box(x, 0, width, 40),
        "fills": [solid(0.2, 0.2, 0.2)],
        "children": [
            {
                "id": f"I{id_};9:2",
                "name": "Label",
                "type": "TEXT",
                "characters": label,
                "absoluteBoundingBox": box(x + 8, 8, 80, 20),
                "style": {"fontFamily": "Inter", "fontSize": 14},
            }
        ],
    }


def apply_pointer_diff(ref, diff):
    out = copy.deepcopy(ref)
    for path, value in diff.items():
        parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
        target = out
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        last = parts[-1]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return out


def test_identical_instances_collapse_to_reference_plus_diff():
    rows = [instance(f"1:{i}", i * 120, f"Item {i}") for i in range(2, 6)]
    state, note = run(CollapseInstances(), frame("1:1", rows))
    children = state.data[0]["children"]
    assert children[0] == rows[0]
    assert children[1] == {
        "id": "1:3",
        "name": "Row",
        "type": "INSTANCE",
        "sameAs": "1:2",
        "absoluteBoundingBox": box(360, 0, 100, 40),
        "diff": {"/children/0/characters": "Item 3"},
    }
    assert note == "Row×4 (−3 nodes)"
    assert "sameAs" in state.legend["conventions"]


def test_reference_plus_diff_rebuilds_the_instance():
    from figma_fit.passes.figma_instances import _normalize

    a = instance("1:2", 0, "One")
    b = instance("1:3", 500, "Two")
    b["children"][0]["absoluteBoundingBox"]["y"] = 12  # an override that moves the label
    state, _ = run(CollapseInstances(), frame("1:1", [a, b]))
    short = state.data[0]["children"][1]
    assert apply_pointer_diff(_normalize(a), short["diff"]) == _normalize(b)


@pytest.mark.parametrize(
    "other",
    [
        lambda: instance("1:3", 200, "x", props="B"),  # different variant
        lambda: instance("1:3", 200, "x", width=300),  # different size
        lambda: {**instance("1:3", 200, "x"), "children": []},  # different shape
    ],
)
def test_instances_that_differ_structurally_are_kept_whole(other):
    second = other()
    state, note = run(CollapseInstances(), frame("1:1", [instance("1:2", 0, "a"), second]))
    assert state.data[0]["children"][1] == second
    assert note == ""


# --- minify -------------------------------------------------------------------


def test_minify_drops_defaults_rewrites_and_shortens_keys():
    node = {
        "id": "1:1",
        "name": "Card",
        "type": "FRAME",
        "visible": True,
        "opacity": 1,
        "blendMode": "PASS_THROUGH",
        "absoluteBoundingBox": box(0.0, 10.123456, 320, 48.40000152587891),
        "absoluteRenderBounds": box(0, 10, 320, 48),
        "fills": [solid(0.0666666701436043, 0.0941176488995552, 0.15294118225574493)],
        "strokes": [],
        "cornerRadius": 8,
        "children": [],
    }
    state, note = run(figma_minify(), node)
    assert state.data == [
        {
            "id": "1:1",
            "name": "Card",
            "type": "FRAME",
            "box": [0, 10.12, 320, 48.4],
            "fills": [{"type": "SOLID", "color": "#111827"}],
            "radius": 8,
        }
    ]
    assert state.legend["keys"] == {
        "box": "absoluteBoundingBox as [x, y, width, height]",
        "radius": "cornerRadius",
    }
    assert "lossy" not in note  # box floats are rounded by the box rewrite, reported as rewritten


def test_minify_keeps_node_level_normal_blend_and_alpha():
    node = {
        "id": "1:1",
        "blendMode": "NORMAL",
        "fills": [{**solid(1, 0, 0), "color": {"r": 1, "g": 0, "b": 0, "a": 0.5}}],
    }
    state, _ = run(figma_minify(), node)
    assert state.data[0] == {
        "id": "1:1",
        "blendMode": "NORMAL",
        "fills": [{"type": "SOLID", "color": "#ff000080"}],
    }


def test_minify_rewrites_diff_pointers_and_keeps_their_values():
    node = {
        "id": "1:3",
        "sameAs": "1:2",
        "diff": {
            "/children/0/characters": "",
            "/children/0/absoluteBoundingBox": box(1, 2, 3, 4),
            "/visible": True,
        },
    }
    state, _ = run(figma_minify(), node)
    assert state.data[0]["diff"] == {
        "/children/0/text": "",
        "/children/0/box": [1, 2, 3, 4],
        "/visible": True,
    }


def test_minify_processes_legend_styles():
    state = State([{"id": "1:1", "fills": "@p1"}], {"styles": {"p1": [solid(1, 1, 1)]}})
    state, _ = figma_minify()(state)
    assert state.legend["styles"] == {"p1": [{"type": "SOLID", "color": "#ffffff"}]}


def test_generic_minify_rounds_and_reports_lossy():
    state, note = Minify(MinifyRules(decimals=1))(State([{"a": 1.26, "b": [2.04]}]))
    assert state.data == [{"a": 1.3, "b": [2]}]
    assert note == "2 floats rounded (lossy)"
