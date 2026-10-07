from figma_fit.models import State
from figma_fit.pipeline import compact, effective_limit
from figma_fit.tokens import ByteRatioEstimator, serialize

EXACT = ByteRatioEstimator(1)  # 1 token per byte: easy to reason about


class Halve:
    """Test pass: keeps the first half of a list."""

    def __init__(self, name):
        self.name = name
        self.calls = 0

    def __call__(self, state):
        self.calls += 1
        data = state.data[: len(state.data) // 2]
        removed = len(state.data) - len(data)
        return State(data, state.legend), f"−{removed}" if removed else ""


def render(state, notes):
    return serialize(state.data)


def test_stops_as_soon_as_output_fits():
    a, b, c = Halve("a"), Halve("b"), Halve("c")
    data = list(range(100))
    limit = len(serialize(data[:50]))
    result = compact(data, [a, b, c], render, limit, estimator=EXACT)
    assert result.fits
    assert (a.calls, b.calls, c.calls) == (1, 0, 0)
    assert result.state.data == data[:50]
    assert [n.pass_name for n in result.notes] == ["a"]
    assert result.notes[0].removed == "−50"


def test_runs_no_pass_when_already_within_limit():
    a = Halve("a")
    result = compact([1, 2], [a], render, 1000, estimator=EXACT)
    assert result.fits and a.calls == 0 and result.notes == ()


def test_reports_not_fitting_after_every_pass():
    passes = [Halve("a"), Halve("b")]
    result = compact(list(range(1000)), passes, render, 10, estimator=EXACT)
    assert not result.fits
    assert result.tokens == EXACT.count(result.text) > 10


def test_no_op_passes_leave_no_note():
    class Noop:
        name = "noop"

        def __call__(self, state):
            return state, ""

    result = compact(list(range(100)), [Noop()], render, 10, estimator=EXACT)
    assert result.notes == ()


def test_effective_limit_applies_safety_margin():
    assert effective_limit(20_000) == 16_000
    assert effective_limit(1001, 0.5) == 500
