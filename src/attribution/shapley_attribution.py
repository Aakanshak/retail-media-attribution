"""Exact Shapley-value channel attribution for a capped player set."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from src.attribution.common import Journey, channel_sequence


@dataclass(frozen=True)
class ShapleyResult:
    """Exact cooperative-game values and normalized channel credit."""

    selected_channels: tuple[str, ...]
    coalition_values: dict[frozenset[str], float]
    shapley_values: dict[str, float]
    normalized_credit: dict[str, float]


def select_top_channels(
    journeys: Iterable[Journey],
    granularity: str,
    max_channels: int,
) -> tuple[str, ...]:
    """Rank channels by converted-path presence, then total-path presence."""

    converted_presence: Counter[str] = Counter()
    total_presence: Counter[str] = Counter()
    for journey in journeys:
        channels = set(channel_sequence(journey.touchpoints, granularity))
        total_presence.update(channels)
        if journey.converted:
            converted_presence.update(channels)
    ranked = sorted(
        total_presence,
        key=lambda channel: (
            converted_presence[channel],
            total_presence[channel],
            channel,
        ),
        reverse=True,
    )
    return tuple(ranked[:max_channels])


def all_coalitions(players: tuple[str, ...]) -> list[frozenset[str]]:
    """Enumerate every subset of players, including the empty coalition."""

    return [
        frozenset(coalition)
        for size in range(len(players) + 1)
        for coalition in combinations(players, size)
    ]


def estimate_coalition_values(
    journeys: Iterable[Journey],
    players: tuple[str, ...],
    granularity: str,
    smoothing: float = 1.0,
) -> dict[frozenset[str], float]:
    """Estimate v(S) as smoothed conversion rate when only channels in S exist.

    Each observed journey is projected onto the selected player set. For a
    coalition S, evidence consists of paths whose observed player set is a
    subset of S. This produces a consistent "channels available" game and lets
    both converted and non-converted paths inform the value function.
    """

    if smoothing < 0:
        raise ValueError("smoothing must be non-negative")
    observations: list[tuple[frozenset[str], bool]] = []
    allowed = set(players)
    for journey in journeys:
        observed = frozenset(
            channel_sequence(
                journey.touchpoints,
                granularity,
                allowed_channels=allowed,
            )
        )
        observations.append((observed, journey.converted))

    global_rate = (
        sum(converted for _, converted in observations) / len(observations)
        if observations
        else 0.0
    )
    values: dict[frozenset[str], float] = {}
    for coalition in all_coalitions(players):
        eligible = [
            converted
            for observed, converted in observations
            if observed and observed.issubset(coalition)
        ]
        conversions = sum(eligible)
        values[coalition] = (
            conversions + smoothing * global_rate
        ) / (len(eligible) + smoothing) if eligible or smoothing else 0.0
    values[frozenset()] = 0.0
    return values


def exact_shapley_values(
    players: tuple[str, ...],
    coalition_values: dict[frozenset[str], float],
) -> dict[str, float]:
    """Average each player's marginal contribution over all coalitions.

    Exact Shapley evaluation is O(2^n): every additional channel doubles the
    coalition count. The public fitting function therefore caps the game at
    6-8 high-volume channels by default rather than pretending 20+ channels are
    computationally cheap.
    """

    player_count = len(players)
    factorial = math.factorial
    denominator = factorial(player_count)
    values: dict[str, float] = {}
    for player in players:
        others = tuple(candidate for candidate in players if candidate != player)
        contribution = 0.0
        for size in range(len(others) + 1):
            weight = (
                factorial(size)
                * factorial(player_count - size - 1)
                / denominator
            )
            for coalition_tuple in combinations(others, size):
                coalition = frozenset(coalition_tuple)
                marginal = (
                    coalition_values[coalition | {player}]
                    - coalition_values[coalition]
                )
                contribution += weight * marginal
        values[player] = contribution
    return values


def fit_shapley_attribution(
    journeys: Iterable[Journey],
    granularity: str = "campaign_type_placement",
    max_channels: int = 8,
    smoothing: float = 1.0,
) -> ShapleyResult:
    """Fit an exact capped Shapley game and normalize positive contributions."""

    if not 1 <= max_channels <= 10:
        raise ValueError("max_channels must be between 1 and 10")
    journeys = list(journeys)
    players = select_top_channels(journeys, granularity, max_channels)
    coalition_values = estimate_coalition_values(
        journeys, players, granularity, smoothing
    )
    shapley_values = exact_shapley_values(players, coalition_values)
    positive = {
        channel: max(0.0, value)
        for channel, value in shapley_values.items()
    }
    total = sum(positive.values())
    normalized = (
        {channel: value / total for channel, value in positive.items()}
        if total > 0
        else {channel: 1.0 / len(players) for channel in players}
        if players
        else {}
    )
    return ShapleyResult(
        selected_channels=players,
        coalition_values=coalition_values,
        shapley_values=shapley_values,
        normalized_credit=normalized,
    )

