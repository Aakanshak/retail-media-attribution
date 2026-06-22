"""First-order Markov-chain attribution using channel removal effects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from src.attribution.common import Journey, channel_sequence


START = "Start"
CONVERSION = "Conversion"
NULL = "Null/No Conversion"
ABSORBING_STATES = (CONVERSION, NULL)


@dataclass(frozen=True)
class MarkovResult:
    """Markov transition and removal-effect outputs."""

    states: tuple[str, ...]
    transition_matrix: np.ndarray
    baseline_conversion_probability: float
    removal_effects: dict[str, float]
    normalized_credit: dict[str, float]


def journey_state_paths(
    journeys: Iterable[Journey],
    granularity: str = "campaign_type_placement",
    removed_channel: str | None = None,
) -> list[list[str]]:
    """Build Start -> channel states -> absorbing outcome paths."""

    paths: list[list[str]] = []
    for journey in journeys:
        channels = channel_sequence(journey.touchpoints, granularity)
        if removed_channel is not None:
            channels = [channel for channel in channels if channel != removed_channel]
            # Removing a state can make formerly separated duplicate states adjacent.
            channels = [
                channel
                for index, channel in enumerate(channels)
                if index == 0 or channel != channels[index - 1]
            ]
        outcome = CONVERSION if journey.converted else NULL
        paths.append([START, *channels, outcome])
    return paths


def transition_probability_matrix(
    paths: Iterable[list[str]],
) -> tuple[tuple[str, ...], np.ndarray]:
    """Estimate P(next state | current state) from observed path transitions."""

    paths = list(paths)
    channels = sorted(
        {
            state
            for path in paths
            for state in path
            if state not in {START, CONVERSION, NULL}
        }
    )
    states = (START, *channels, CONVERSION, NULL)
    state_index = {state: index for index, state in enumerate(states)}
    transition_counts: Counter[tuple[str, str]] = Counter()
    outgoing_counts: Counter[str] = Counter()

    for path in paths:
        for origin, destination in zip(path, path[1:]):
            transition_counts[(origin, destination)] += 1
            outgoing_counts[origin] += 1

    matrix = np.zeros((len(states), len(states)), dtype=float)
    for (origin, destination), count in transition_counts.items():
        matrix[state_index[origin], state_index[destination]] = (
            count / outgoing_counts[origin]
        )
    matrix[state_index[CONVERSION], state_index[CONVERSION]] = 1.0
    matrix[state_index[NULL], state_index[NULL]] = 1.0
    return states, matrix


def conversion_probability(
    states: tuple[str, ...],
    transition_matrix: np.ndarray,
) -> float:
    """Compute Start's eventual conversion probability via an absorbing chain.

    If Q contains transitions among transient states and R contains transitions
    from transient to absorbing states, N = (I - Q)^-1 is the fundamental
    matrix. N @ R gives eventual absorption probabilities. Solving the linear
    system is numerically preferable to explicitly calculating the inverse.
    """

    transient_indices = [
        index
        for index, state in enumerate(states)
        if state not in ABSORBING_STATES
    ]
    absorbing_indices = [states.index(CONVERSION), states.index(NULL)]
    q_matrix = transition_matrix[np.ix_(transient_indices, transient_indices)]
    r_matrix = transition_matrix[np.ix_(transient_indices, absorbing_indices)]
    identity = np.eye(len(transient_indices))
    try:
        absorption = np.linalg.solve(identity - q_matrix, r_matrix)
    except np.linalg.LinAlgError:
        absorption = np.linalg.pinv(identity - q_matrix) @ r_matrix
    start_row = transient_indices.index(states.index(START))
    conversion_column = absorbing_indices.index(states.index(CONVERSION))
    return float(np.clip(absorption[start_row, conversion_column], 0.0, 1.0))


def remove_channel_from_matrix(
    states: tuple[str, ...],
    transition_matrix: np.ndarray,
    channel: str,
) -> tuple[tuple[str, ...], np.ndarray]:
    """Delete a channel and redirect inbound probability to the Null state.

    Redirecting lost inbound probability to Null models the counterfactual that
    traffic dependent on the removed channel does not magically skip ahead to
    its next observed touchpoint.
    """

    if channel in {START, CONVERSION, NULL}:
        raise ValueError("absorbing and Start states cannot be removed")
    removed_index = states.index(channel)
    null_index = states.index(NULL)
    keep_indices = [
        index for index in range(len(states)) if index != removed_index
    ]
    reduced_states = tuple(states[index] for index in keep_indices)
    reduced = transition_matrix[np.ix_(keep_indices, keep_indices)].copy()
    reduced_null_index = reduced_states.index(NULL)

    for reduced_row, original_row in enumerate(keep_indices):
        lost_probability = transition_matrix[original_row, removed_index]
        reduced[reduced_row, reduced_null_index] += lost_probability

    # The removed row is discarded. Remaining row sums stay at one because all
    # inbound probability to the removed state was redirected to Null.
    return reduced_states, reduced


def fit_markov_attribution(
    journeys: Iterable[Journey],
    granularity: str = "campaign_type_placement",
) -> MarkovResult:
    """Fit a Markov model and normalize positive channel removal effects."""

    journeys = list(journeys)
    paths = journey_state_paths(journeys, granularity)
    states, matrix = transition_probability_matrix(paths)
    baseline = conversion_probability(states, matrix)
    channels = [
        state for state in states if state not in {START, CONVERSION, NULL}
    ]
    removal_effects: dict[str, float] = {}

    for channel in channels:
        removed_states, removed_matrix = remove_channel_from_matrix(
            states, matrix, channel
        )
        removed_probability = conversion_probability(removed_states, removed_matrix)
        removal_effects[channel] = max(0.0, baseline - removed_probability)

    total_effect = sum(removal_effects.values())
    if total_effect > 0:
        normalized = {
            channel: effect / total_effect
            for channel, effect in removal_effects.items()
        }
    else:
        normalized = {
            channel: 1.0 / len(channels)
            for channel in channels
        } if channels else {}

    return MarkovResult(
        states=states,
        transition_matrix=matrix,
        baseline_conversion_probability=baseline,
        removal_effects=removal_effects,
        normalized_credit=normalized,
    )
