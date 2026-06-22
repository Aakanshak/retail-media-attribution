"""Transparent heuristic attribution models.

Each function returns one fractional credit per input touchpoint. Credits are
aligned to the original list, non-marketing outcome events receive zero, and a
converted path always sums to 1.0.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

from src.attribution.common import (
    conversion_timestamp,
    is_converted,
    marketing_touchpoint_indices,
    validate_credit_vector,
)


Touchpoint = dict[str, str]


def _empty_credits(touchpoints: Sequence[Touchpoint]) -> list[float]:
    return [0.0] * len(touchpoints)


def first_touch(touchpoints: Sequence[Touchpoint]) -> list[float]:
    """Give 100% credit to the earliest eligible marketing touch."""

    credits = _empty_credits(touchpoints)
    eligible = marketing_touchpoint_indices(touchpoints)
    if is_converted(touchpoints) and eligible:
        first_index = min(
            eligible,
            key=lambda index: pd.Timestamp(touchpoints[index]["timestamp"]),
        )
        credits[first_index] = 1.0
    validate_credit_vector(credits, touchpoints)
    return credits


def last_touch(touchpoints: Sequence[Touchpoint]) -> list[float]:
    """Give 100% credit to the final eligible marketing touch."""

    credits = _empty_credits(touchpoints)
    eligible = marketing_touchpoint_indices(touchpoints)
    if is_converted(touchpoints) and eligible:
        last_index = max(
            eligible,
            key=lambda index: pd.Timestamp(touchpoints[index]["timestamp"]),
        )
        credits[last_index] = 1.0
    validate_credit_vector(credits, touchpoints)
    return credits


def linear(touchpoints: Sequence[Touchpoint]) -> list[float]:
    """Split credit equally across every eligible marketing touchpoint."""

    credits = _empty_credits(touchpoints)
    eligible = marketing_touchpoint_indices(touchpoints)
    if is_converted(touchpoints) and eligible:
        equal_credit = 1.0 / len(eligible)
        for index in eligible:
            credits[index] = equal_credit
    validate_credit_vector(credits, touchpoints)
    return credits


def time_decay(
    touchpoints: Sequence[Touchpoint],
    half_life_days: float = 7.0,
) -> list[float]:
    """Weight recent touches more heavily using exponential half-life decay."""

    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")

    credits = _empty_credits(touchpoints)
    eligible = marketing_touchpoint_indices(touchpoints)
    conversion_time = conversion_timestamp(touchpoints)
    if conversion_time is not None and eligible:
        decay_rate = math.log(2) / half_life_days
        raw_weights = []
        for index in eligible:
            touch_time = pd.Timestamp(touchpoints[index]["timestamp"])
            age_days = max(
                0.0,
                (conversion_time - touch_time).total_seconds() / 86_400,
            )
            raw_weights.append(math.exp(-decay_rate * age_days))

        denominator = sum(raw_weights)
        for index, weight in zip(eligible, raw_weights):
            credits[index] = weight / denominator
    validate_credit_vector(credits, touchpoints)
    return credits


FIRST_TOUCH = first_touch
LAST_TOUCH = last_touch
LINEAR = linear
TIME_DECAY = time_decay

