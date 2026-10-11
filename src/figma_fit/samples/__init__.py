"""A built-in sample design, so figma-fit can be tried with no token or request.

shop.json is a saved Figma API response for a synthetic dashboard (from
tests/synth.py): repeated rows, hidden and off-canvas layers, wrapper groups
and repeated styles, about 38k tokens before compaction.
"""

from __future__ import annotations

import json
from importlib.resources import files

from figma_fit.figma import FetchedNode, nodes_from_body

SAMPLE_FILE_KEY = "sample"


def load_sample() -> list[FetchedNode]:
    text = files(__package__).joinpath("shop.json").read_text(encoding="utf-8")
    return nodes_from_body(SAMPLE_FILE_KEY, json.loads(text))
