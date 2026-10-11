from figma_fit.split import node_sizes, plan_split
from figma_fit.tokens import ByteRatioEstimator, serialize

EXACT = ByteRatioEstimator(1)


def node(id_, children=(), text=""):
    n = {"id": id_, "name": f"n{id_}", "type": "FRAME", "text": text}
    if children:
        n["children"] = list(children)
    return n


def all_ids(n):
    yield n["id"]
    for c in n.get("children", ()):
        yield from all_ids(c)


def test_node_sizes_never_undercount_the_whole_subtree():
    root = node("1", [node("2", [node("3", text="x" * 50)]), node("4", text="y" * 7)])
    sizes = node_sizes([root], ByteRatioEstimator(3.2))
    assert sizes[id(root)] >= ByteRatioEstimator(3.2).count(serialize(root))
    exact = node_sizes([root], EXACT)
    assert exact[id(root)] == len(serialize(root))  # exact when 1 token = 1 byte


def test_small_tree_is_one_group():
    root = node("1", [node("2"), node("3")])
    plan = plan_split([root], limit=10_000, envelope=100, estimator=EXACT)
    assert [g.node_ids for g in plan.groups] == [["1"]]
    assert plan.oversize == ()


def test_oversized_nodes_are_replaced_by_children_and_packed_in_order():
    kids = [node(str(i), text="x" * 100) for i in range(2, 12)]
    root = node("1", kids)
    plan = plan_split([root], limit=400, envelope=50, estimator=EXACT)
    planned = [i for g in plan.groups for i in g.node_ids]
    assert planned == [str(i) for i in range(2, 12)]  # every child, document order
    assert all(g.est_tokens <= 400 for g in plan.groups)
    assert len(plan.groups) > 1
    assert all(len(g.items) >= 2 for g in plan.groups[:-1])  # small siblings share calls


def test_group_estimate_covers_the_items_and_envelope():
    kids = [node(str(i), text="x" * 100) for i in range(2, 6)]
    plan = plan_split([node("1", kids)], limit=400, envelope=50, estimator=EXACT)
    for g in plan.groups:
        data = serialize([k for k in kids if k["id"] in g.node_ids])
        assert g.est_tokens >= 50 + len(data) - 2  # minus the list brackets


def test_leaf_too_big_on_its_own_is_oversize_not_data():
    root = node("1", [node("2", text="x" * 5000), node("3")])
    plan = plan_split([root], limit=400, envelope=50, estimator=EXACT)
    assert [o.node_id for o in plan.oversize] == ["2"]
    assert [g.node_ids for g in plan.groups] == [["3"]]


def test_node_with_many_small_children_is_split_not_oversize():
    # The commas between 1000 children must not count as the parent's own fields.
    root = node("1", [node(str(i)) for i in range(2, 1002)])
    plan = plan_split([root], limit=600, envelope=50, estimator=EXACT)
    assert plan.oversize == ()
    assert [i for g in plan.groups for i in g.node_ids] == [str(i) for i in range(2, 1002)]


def test_node_whose_own_fields_are_too_big_is_oversize():
    root = node("1", [node("2")], text="z" * 5000)
    plan = plan_split([root], limit=400, envelope=50, estimator=EXACT)
    assert [o.node_id for o in plan.oversize] == ["1"]
    assert plan.groups == ()
