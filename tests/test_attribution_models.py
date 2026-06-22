"""Attribution model invariants and small known examples."""

from __future__ import annotations

import math

import numpy as np

from src.attribution.common import Journey
from src.attribution.markov_chain_attribution import fit_markov_attribution
from src.attribution.rule_based_models import (
    first_touch,
    last_touch,
    linear,
    time_decay,
)
from src.attribution.shapley_attribution import fit_shapley_attribution


def touch(timestamp: str, channel: str, event_type: str) -> dict[str, str]:
    return {
        "timestamp": timestamp,
        "campaign_type": channel,
        "placement": "test",
        "event_type": event_type,
        "campaign_id": "CAM00001",
        "event_id": "EVT0000000001",
    }


CONVERTED_PATH = [
    touch("2025-01-01", "Display", "impression"),
    touch("2025-01-05", "Sponsored Brand", "click"),
    touch("2025-01-08", "Sponsored Product", "click"),
    touch("2025-01-08", "Sponsored Product", "purchase"),
]


def test_rule_based_models_sum_to_one_and_ignore_purchase():
    first = first_touch(CONVERTED_PATH)
    last = last_touch(CONVERTED_PATH)
    equal = linear(CONVERTED_PATH)
    decay = time_decay(CONVERTED_PATH)

    for credits in [first, last, equal, decay]:
        assert math.isclose(sum(credits), 1.0)
        assert credits[-1] == 0
    assert first[0] == 1
    assert last[2] == 1
    assert equal[:3] == [1 / 3, 1 / 3, 1 / 3]
    assert decay[2] > decay[1] > decay[0]


def test_nonconverting_rule_path_gets_zero_credit():
    path = CONVERTED_PATH[:-1]
    assert sum(first_touch(path)) == 0
    assert sum(last_touch(path)) == 0
    assert sum(linear(path)) == 0
    assert sum(time_decay(path)) == 0


def test_markov_transition_matrix_and_credit_are_valid():
    journeys = [
        Journey("1", tuple(CONVERTED_PATH), True),
        Journey(
            "2",
            (
                touch("2025-01-01", "Display", "impression"),
                touch("2025-01-02", "Display", "click"),
            ),
            False,
        ),
        Journey(
            "3",
            (
                touch("2025-01-01", "Video", "impression"),
                touch("2025-01-03", "Sponsored Product", "click"),
                touch("2025-01-03", "Sponsored Product", "purchase"),
            ),
            True,
        ),
    ]
    result = fit_markov_attribution(journeys, granularity="campaign_type")

    assert np.allclose(result.transition_matrix.sum(axis=1), 1.0)
    assert 0 <= result.baseline_conversion_probability <= 1
    assert math.isclose(sum(result.normalized_credit.values()), 1.0)
    assert all(value >= 0 for value in result.removal_effects.values())


def test_exact_shapley_credit_sums_to_one():
    journeys = [
        Journey("1", tuple(CONVERTED_PATH), True),
        Journey("2", tuple(CONVERTED_PATH[:-1]), False),
        Journey(
            "3",
            (
                touch("2025-01-01", "Video", "impression"),
                touch("2025-01-03", "Video", "click"),
            ),
            False,
        ),
    ]
    result = fit_shapley_attribution(
        journeys,
        granularity="campaign_type",
        max_channels=4,
    )

    assert len(result.coalition_values) == 2 ** len(result.selected_channels)
    assert math.isclose(sum(result.normalized_credit.values()), 1.0)
    assert all(value >= 0 for value in result.normalized_credit.values())


def test_every_rule_model_conserves_credit_across_converted_paths():
    converted_paths = [
        CONVERTED_PATH,
        [
            touch("2025-02-01", "Video", "impression"),
            touch("2025-02-07", "Sponsored Product", "click"),
            touch("2025-02-07", "Sponsored Product", "purchase"),
        ],
    ]

    for path in converted_paths:
        for model in [first_touch, last_touch, linear, time_decay]:
            credits = model(path)
            assert math.isclose(sum(credits), 1.0, abs_tol=1e-9)
            assert all(credit >= 0 for credit in credits)
