import math

import pytest

from figma_fit.tokens import ByteRatioEstimator, estimate, serialize


def test_serialize_is_compact_and_keeps_unicode():
    assert serialize({"a": [1, 2], "b": "€"}) == '{"a":[1,2],"b":"€"}'


def test_estimate_counts_the_serialized_string():
    obj = {"name": "Card", "children": []}
    assert estimate(obj) == estimate(serialize(obj))


def test_estimate_rounds_up():
    assert ByteRatioEstimator(4).count("abcde") == 2
    assert ByteRatioEstimator(4).count("") == 0


def test_non_ascii_costs_more_than_ascii_of_same_length():
    assert estimate("€€€€€€€€") > estimate("abcdefgh")


def test_default_ratio_is_more_conservative_than_chars_over_four(pricing_body):
    text = serialize(pricing_body)
    assert estimate(text) > math.ceil(len(text) / 4)


def test_ratio_must_be_positive():
    with pytest.raises(ValueError):
        ByteRatioEstimator(0)
