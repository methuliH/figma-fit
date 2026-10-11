"""Compare figma-fit's token estimates with real Claude token counts (PLAN.md, M5).

    uv run --group calibrate python scripts/calibrate.py [capture.json ...]

Uses the recorded REST responses in captures/ (and tests/fixtures/) by
default. For each frame and several budgets it renders the exact tool output,
counts it with Anthropic's token-counting endpoint, and prints the ratio of
estimate to actual. Needs ANTHROPIC_API_KEY or an `ant auth login` profile.
Token counting is free, but rate-limited.

Outputs are held to budget * SAFETY estimated tokens, so the real count fits
the budget whenever estimate/actual >= SAFETY. Tune DEFAULT_BYTES_PER_TOKEN
(and then SAFETY) so the minimum ratio clears SAFETY with room to spare.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import anthropic

from figma_fit.figma import FetchedNode, nodes_from_body
from figma_fit.fit import fit_nodes
from figma_fit.pipeline import SAFETY
from figma_fit.tokens import DEFAULT_ESTIMATOR, serialize

MODEL = "claude-opus-5-5"
BUDGETS = (2_000, 8_000, 25_000)


def load(path: Path) -> list[FetchedNode]:
    return nodes_from_body(path.stem, json.loads(path.read_text(encoding="utf-8")))


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or sorted(
        [*Path("captures").glob("*.json"), *Path("tests/fixtures").glob("*.json")]
    )
    if not paths:
        sys.exit("no captures found; record some with scripts/record_fixture.py")

    client = anthropic.Anthropic()

    def count(text: str) -> int:
        return client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": text}]
        ).input_tokens

    overhead = count("x") - 1  # message framing, not part of the tool output

    ratios: list[float] = []
    columns = ("budget", "status", "bytes", "est", "actual", "ratio")
    print(f"{'frame':30} " + " ".join(f"{c:>7}" for c in columns))
    for path in paths:
        for fetched in load(path):
            texts = {("raw", 0): serialize(fetched.document)}
            for budget in BUDGETS:
                result = fit_nodes([fetched], budget)
                texts[(result.status, budget)] = result.text
            for (status, budget), text in texts.items():
                est = DEFAULT_ESTIMATOR.count(text)
                actual = max(count(text) - overhead, 1)
                ratio = est / actual
                ratios.append(ratio)
                name = f"{path.stem}:{fetched.node_id}"[:30]
                print(
                    f"{name:30} {budget:>7} {status:>6} {len(text.encode()):>9} "
                    f"{est:>7} {actual:>7} {ratio:>6.2f}"
                )

    ratios.sort()
    p5 = ratios[max(0, int(len(ratios) * 0.05) - 1)]
    print(
        f"\n{len(ratios)} outputs · estimate/actual: min {ratios[0]:.2f} · p5 {p5:.2f} · "
        f"median {statistics.median(ratios):.2f} · max {ratios[-1]:.2f}"
    )
    # Output is held to budget * SAFETY estimated tokens, so the real count stays within
    # the budget as long as estimate/actual >= SAFETY.
    if ratios[0] < SAFETY:
        print(f"Guarantee AT RISK: min ratio < SAFETY ({SAFETY}). Lower DEFAULT_BYTES_PER_TOKEN.")
    else:
        print(f"Guarantee holds on this set (min ratio >= SAFETY {SAFETY}).")


if __name__ == "__main__":
    main()
