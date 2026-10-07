"""Token estimation.

The estimate is applied to the exact string the tool will return, never to
the Python object, so serialization choices are counted too.
"""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

# Dense JSON (ids, hex colours, punctuation) tokenizes worse than prose, so
# the common chars/4 rule underestimates. 3.2 is a conservative starting point
# until calibrated against real counts (PLAN.md, M5).
DEFAULT_BYTES_PER_TOKEN = 3.2


class Estimator(Protocol):
    def count(self, text: str) -> int: ...


class ByteRatioEstimator:
    """Estimate tokens as UTF-8 bytes / ratio.

    Bytes rather than characters: non-ASCII text (CJK labels, emoji) costs more
    tokens per character, and over-estimating keeps the budget guarantee safe.
    """

    def __init__(self, bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN) -> None:
        if bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be positive")
        self.bytes_per_token = bytes_per_token

    def count(self, text: str) -> int:
        return math.ceil(len(text.encode("utf-8")) / self.bytes_per_token)


DEFAULT_ESTIMATOR: Estimator = ByteRatioEstimator()


def serialize(obj: Any) -> str:
    """Compact JSON: no whitespace, non-ASCII kept as-is (escapes cost tokens)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def estimate(obj: Any, estimator: Estimator = DEFAULT_ESTIMATOR) -> int:
    """Estimate tokens for a string, or for an object as it would be serialized."""
    text = obj if isinstance(obj, str) else serialize(obj)
    return estimator.count(text)
