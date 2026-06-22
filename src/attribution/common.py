"""Shared journey parsing and channel utilities for attribution models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


MARKETING_EVENT_TYPES = frozenset({"impression", "click"})
CONVERSION_EVENT_TYPE = "purchase"


@dataclass(frozen=True)
class Journey:
    """Analysis-ready customer path."""

    path_id: str
    touchpoints: tuple[dict[str, str], ...]
    converted: bool
    order_id: str | None = None
    revenue: float = 0.0


def channel_name(
    touchpoint: dict[str, str],
    granularity: str = "campaign_type_placement",
) -> str:
    """Return a stable channel label at the requested reporting grain."""

    campaign_type = touchpoint["campaign_type"]
    placement = touchpoint["placement"]
    if granularity == "campaign_type":
        return campaign_type
    if granularity == "placement":
        return placement
    if granularity == "campaign_type_placement":
        return f"{campaign_type} | {placement}"
    raise ValueError(
        "granularity must be campaign_type, placement, or campaign_type_placement"
    )


def marketing_touchpoint_indices(
    touchpoints: Sequence[dict[str, str]],
) -> list[int]:
    """Return indices for credit-eligible ad exposures and interactions."""

    return [
        index
        for index, touchpoint in enumerate(touchpoints)
        if touchpoint.get("event_type") in MARKETING_EVENT_TYPES
    ]


def is_converted(touchpoints: Sequence[dict[str, str]]) -> bool:
    """Infer conversion from the presence of a purchase outcome touchpoint."""

    return any(
        touchpoint.get("event_type") == CONVERSION_EVENT_TYPE
        for touchpoint in touchpoints
    )


def conversion_timestamp(
    touchpoints: Sequence[dict[str, str]],
) -> pd.Timestamp | None:
    """Return the purchase timestamp for a converted path."""

    purchase_times = [
        pd.Timestamp(touchpoint["timestamp"])
        for touchpoint in touchpoints
        if touchpoint.get("event_type") == CONVERSION_EVENT_TYPE
    ]
    return max(purchase_times) if purchase_times else None


def channel_sequence(
    touchpoints: Sequence[dict[str, str]],
    granularity: str = "campaign_type_placement",
    allowed_channels: set[str] | None = None,
    collapse_consecutive: bool = True,
) -> list[str]:
    """Convert ordered touchpoints into a clean marketing-state sequence."""

    ordered = sorted(
        (
            touchpoint
            for touchpoint in touchpoints
            if touchpoint.get("event_type") in MARKETING_EVENT_TYPES
        ),
        key=lambda touchpoint: pd.Timestamp(touchpoint["timestamp"]),
    )
    result: list[str] = []
    for touchpoint in ordered:
        channel = channel_name(touchpoint, granularity)
        if allowed_channels is not None and channel not in allowed_channels:
            continue
        if collapse_consecutive and result and result[-1] == channel:
            continue
        result.append(channel)
    return result


def load_journeys(
    journey_path: Path,
    orders_path: Path | None = None,
) -> list[Journey]:
    """Load CSV journeys and optionally attach order revenue."""

    journeys = pd.read_csv(
        journey_path,
        dtype={
            "path_id": "string",
            "ordered_touchpoints": "string",
            "order_id": "string",
        },
    )
    revenue_by_order: dict[str, float] = {}
    if orders_path is not None:
        orders = pd.read_csv(
            orders_path,
            usecols=["order_id", "order_total"],
            dtype={"order_id": "string"},
        )
        revenue_by_order = dict(
            zip(orders["order_id"], orders["order_total"].astype(float))
        )

    result: list[Journey] = []
    for row in journeys.itertuples(index=False):
        order_id = None if pd.isna(row.order_id) else str(row.order_id)
        result.append(
            Journey(
                path_id=str(row.path_id),
                touchpoints=tuple(json.loads(row.ordered_touchpoints)),
                converted=bool(row.conversion_flag),
                order_id=order_id,
                revenue=revenue_by_order.get(order_id, 0.0),
            )
        )
    return result


def validate_credit_vector(
    credits: Sequence[float],
    touchpoints: Sequence[dict[str, str]],
    tolerance: float = 1e-9,
) -> None:
    """Raise when a rule-based credit vector violates attribution invariants."""

    if len(credits) != len(touchpoints):
        raise ValueError("credit vector length does not match touchpoint count")
    expected = 1.0 if is_converted(touchpoints) else 0.0
    if abs(sum(credits) - expected) > tolerance:
        raise ValueError(
            f"credits sum to {sum(credits):.12f}; expected {expected:.1f}"
        )
    if any(credit < -tolerance for credit in credits):
        raise ValueError("attribution credits cannot be negative")


def unique_channels(
    journeys: Iterable[Journey],
    granularity: str = "campaign_type_placement",
) -> list[str]:
    """Return sorted channel labels observed across journeys."""

    channels: set[str] = set()
    for journey in journeys:
        channels.update(channel_sequence(journey.touchpoints, granularity))
    return sorted(channels)

