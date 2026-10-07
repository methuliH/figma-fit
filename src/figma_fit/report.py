"""The one-line size report at the top of every response."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from figma_fit.models import PassNote
from figma_fit.tokens import DEFAULT_ESTIMATOR, Estimator


def fmt_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 100_000:
        return f"{n / 1000:.1f}k"
    return f"{round(n / 1000)}k"


def report_line(
    *,
    status: str,
    tokens: int,
    budget: int,
    original: int,
    notes: Sequence[PassNote],
) -> str:
    """One line, e.g.

    ``figma-fit: 18.2k/25k tokens (est.) · saved 61% from 46.9k · drop_invisible −41 nodes``
    """
    parts = [f"figma-fit: {fmt_tokens(tokens)}/{fmt_tokens(budget)} tokens (est.)"]
    if status == "fit":
        if original > tokens:
            saved = round(100 * (original - tokens) / original)
            parts.append(f"saved {saved}% from {fmt_tokens(original)}")
    else:
        parts.append(f"SPLIT: {fmt_tokens(original)} of data does not fit, see calls")
    parts.extend(f"{n.pass_name} {n.removed}" for n in notes)
    return " · ".join(parts)


def with_own_count(
    build: Callable[[int], str], estimator: Estimator = DEFAULT_ESTIMATOR
) -> tuple[str, int]:
    """Render text that states its own token count, and return (text, count).

    The count shown is never below the count of the returned text.
    """
    shown = 0
    for _ in range(5):
        text = build(shown)
        actual = estimator.count(text)
        if actual <= shown:
            return text, actual
        shown = actual
    text = build(shown)  # still growing (digit roll-over): settle on an upper bound
    shown = estimator.count(text) + 8
    text = build(shown)
    return text, estimator.count(text)
