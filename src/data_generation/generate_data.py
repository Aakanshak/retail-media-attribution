"""Generate reproducible synthetic retail-media and attribution data.

The full run is deliberately written in chunks: the ad event fact table is too
large to hold comfortably in memory on a typical laptop. Dimension tables and
the much smaller order/journey artifacts stay in memory for readable logic.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from faker import Faker


START_DATE = pd.Timestamp("2024-01-01")
END_DATE = pd.Timestamp("2025-06-30")
DEFAULT_SEED = 42
DEFAULT_TARGET_EVENTS = 9_000_000
LOOKBACK_DAYS = 14
ORGANIC_HOLDOUT_RATE = 0.08

CATEGORIES: dict[str, list[str]] = {
    "Snacks": ["Chips", "Cookies", "Crackers", "Nutrition Bars"],
    "Beverages": ["Coffee", "Tea", "Soda", "Functional Drinks"],
    "Beauty": ["Skin Care", "Hair Care", "Cosmetics", "Fragrance"],
    "Personal Care": ["Oral Care", "Bath", "Deodorant", "Shaving"],
    "Home": ["Cleaning", "Laundry", "Kitchen", "Storage"],
    "Pet": ["Dog Food", "Cat Food", "Treats", "Pet Care"],
    "Baby": ["Diapers", "Feeding", "Baby Care", "Nursery"],
    "Health": ["Vitamins", "First Aid", "Wellness", "OTC"],
}

PRICE_RANGES = {
    "Snacks": (2.49, 14.99),
    "Beverages": (3.49, 29.99),
    "Beauty": (7.99, 79.99),
    "Personal Care": (3.99, 39.99),
    "Home": (4.99, 69.99),
    "Pet": (5.99, 89.99),
    "Baby": (6.99, 74.99),
    "Health": (4.99, 59.99),
}

CAMPAIGN_TYPES = [
    "Sponsored Product",
    "Sponsored Brand",
    "Display",
    "Video",
]

PLACEMENTS_BY_TYPE = {
    "Sponsored Product": (["search_top", "search_carousel", "product_page"], [0.40, 0.38, 0.22]),
    "Sponsored Brand": (["search_top", "search_carousel", "category_page"], [0.45, 0.25, 0.30]),
    "Display": (["product_page", "category_page", "offsite_display"], [0.28, 0.32, 0.40]),
    "Video": (["product_page", "category_page", "offsite_display"], [0.24, 0.31, 0.45]),
}

PROMOTION_WINDOWS = (
    # Weights are intentionally above the desired realized lift because each
    # campaign samples only within its own active dates, which dilutes the
    # portfolio-level spike when campaigns start and end inside a promo window.
    (pd.Timestamp("2024-08-05"), pd.Timestamp("2024-09-08"), 8.5, "back_to_school"),
    (pd.Timestamp("2024-11-18"), pd.Timestamp("2024-12-31"), 13.5, "holiday"),
)


@dataclass(frozen=True)
class GenerationConfig:
    """Runtime controls for data volume and reproducibility."""

    output_dir: Path
    seed: int = DEFAULT_SEED
    target_events: int = DEFAULT_TARGET_EVENTS
    advertisers: int = 50
    products: int = 500
    customers: int = 50_000
    campaigns: int = 300
    chunk_size: int = 250_000
    overwrite: bool = False


def seeded_rng(seed: int) -> tuple[np.random.Generator, Faker]:
    """Return NumPy and Faker generators initialized from the same seed."""

    rng = np.random.default_rng(seed)
    Faker.seed(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    return rng, fake


def promotion_label(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Return the promotion label for each date, or ``none``."""

    date_values = pd.to_datetime(dates)
    labels = np.full(len(date_values), "none", dtype=object)
    for start, end, _, label in PROMOTION_WINDOWS:
        mask = (date_values >= start) & (date_values <= end)
        labels[mask] = label
    return labels


def date_volume_weights(dates: pd.DatetimeIndex) -> np.ndarray:
    """Create normalized traffic weights with weekday and promotion effects."""

    weekday_multiplier = np.where(dates.dayofweek >= 5, 1.30, 1.0)
    trend = np.linspace(0.92, 1.12, len(dates))
    promo_multiplier = np.ones(len(dates))
    for start, end, multiplier, _ in PROMOTION_WINDOWS:
        promo_multiplier[(dates >= start) & (dates <= end)] = multiplier
    weights = weekday_multiplier * trend * promo_multiplier
    return weights / weights.sum()


def generate_advertisers(
    count: int, rng: np.random.Generator, fake: Faker
) -> pd.DataFrame:
    """Generate CPG brands with category and commercial-tier relationships."""

    categories = list(CATEGORIES)
    tiers = rng.choice(
        ["Enterprise", "Mid-Market", "SMB"],
        size=count,
        p=[0.20, 0.35, 0.45],
    )
    category_values = rng.choice(categories, size=count)
    join_dates = pd.to_datetime(
        rng.choice(
            pd.date_range("2022-01-01", "2023-12-15", freq="D"),
            size=count,
        )
    )

    used_names: set[str] = set()
    names: list[str] = []
    suffixes = ["Foods", "Consumer", "Labs", "Essentials", "Naturals", "Brands"]
    while len(names) < count:
        candidate = f"{fake.unique.company().split(',')[0]} {rng.choice(suffixes)}"
        if candidate not in used_names:
            used_names.add(candidate)
            names.append(candidate)

    return pd.DataFrame(
        {
            "advertiser_id": [f"ADV{i:04d}" for i in range(1, count + 1)],
            "brand_name": names,
            "category": category_values,
            "tier": tiers,
            "join_date": join_dates,
        }
    )


def generate_products(
    count: int,
    advertisers: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate products tied to advertiser category and realistic margins."""

    advertiser_indices = np.arange(len(advertisers))
    base_repeats = np.resize(advertiser_indices, count)
    rng.shuffle(base_repeats)

    adjectives = [
        "Classic", "Premium", "Daily", "Ultra", "Natural", "Fresh", "Smart",
        "Essential", "Family", "Active", "Pure", "Signature",
    ]
    formats = [
        "Pack", "Bundle", "Formula", "Collection", "Size", "Kit", "Variety",
    ]
    rows: list[dict[str, object]] = []

    for i, advertiser_idx in enumerate(base_repeats, start=1):
        advertiser = advertisers.iloc[int(advertiser_idx)]
        category = str(advertiser["category"])
        subcategory = str(rng.choice(CATEGORIES[category]))
        low, high = PRICE_RANGES[category]
        price = round(float(np.exp(rng.uniform(np.log(low), np.log(high)))), 2)
        margin_rate = float(rng.uniform(0.28, 0.62))
        cost = round(price * (1 - margin_rate), 2)
        product_name = (
            f"{rng.choice(adjectives)} {subcategory} {rng.choice(formats)} "
            f"{(i % 12) + 1}"
        )
        rows.append(
            {
                "product_id": f"PRD{i:06d}",
                "advertiser_id": advertiser["advertiser_id"],
                "product_name": product_name,
                "category": category,
                "subcategory": subcategory,
                "base_price": price,
                "cost_per_unit": cost,
            }
        )
    return pd.DataFrame(rows)


def generate_customers(
    count: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Generate customers with correlated loyalty, tenure, region, and device."""

    signup_dates = pd.to_datetime(
        rng.choice(pd.date_range("2020-01-01", END_DATE, freq="D"), size=count)
    )
    tenure_days = (END_DATE - signup_dates).days.to_numpy()
    loyalty_score = tenure_days / tenure_days.max() + rng.normal(0, 0.25, count)
    quantiles = np.quantile(loyalty_score, [0.45, 0.75, 0.93])
    loyalty = np.select(
        [
            loyalty_score <= quantiles[0],
            loyalty_score <= quantiles[1],
            loyalty_score <= quantiles[2],
        ],
        ["Bronze", "Silver", "Gold"],
        default="Platinum",
    )
    regions = rng.choice(
        ["Northeast", "Midwest", "South", "West"],
        size=count,
        p=[0.18, 0.21, 0.38, 0.23],
    )
    devices = rng.choice(
        ["mobile", "desktop", "tablet"],
        size=count,
        p=[0.68, 0.26, 0.06],
    )
    return pd.DataFrame(
        {
            "customer_id": [f"CUS{i:07d}" for i in range(1, count + 1)],
            "signup_date": signup_dates,
            "loyalty_tier": loyalty,
            "region": regions,
            "device_preference": devices,
        }
    )


def generate_campaigns(
    count: int,
    advertisers: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate campaigns with budgets and goals driven by advertiser tier."""

    advertiser_indices = np.resize(np.arange(len(advertisers)), count)
    rng.shuffle(advertiser_indices)
    tier_budget = {
        "Enterprise": (1800, 9000),
        "Mid-Market": (600, 3500),
        "SMB": (120, 1200),
    }
    type_acos = {
        "Sponsored Product": 0.24,
        "Sponsored Brand": 0.31,
        "Display": 0.39,
        "Video": 0.46,
    }
    rows: list[dict[str, object]] = []

    for i, advertiser_idx in enumerate(advertiser_indices, start=1):
        advertiser = advertisers.iloc[int(advertiser_idx)]
        campaign_type = str(
            rng.choice(CAMPAIGN_TYPES, p=[0.43, 0.22, 0.22, 0.13])
        )
        start = pd.Timestamp(
            rng.choice(pd.date_range(START_DATE, "2025-05-31", freq="D"))
        )
        duration = int(rng.integers(35, 181))
        end = min(start + pd.Timedelta(days=duration), END_DATE)
        low, high = tier_budget[str(advertiser["tier"])]
        budget = round(float(np.exp(rng.uniform(np.log(low), np.log(high)))), 2)
        target_acos = round(
            float(np.clip(type_acos[campaign_type] + rng.normal(0, 0.045), 0.14, 0.60)),
            3,
        )
        rows.append(
            {
                "campaign_id": f"CAM{i:05d}",
                "advertiser_id": advertiser["advertiser_id"],
                "campaign_name": f"{advertiser['brand_name']} | {campaign_type} | {start:%b %Y}",
                "campaign_type": campaign_type,
                "start_date": start,
                "end_date": end,
                "daily_budget": budget,
                "target_acos": target_acos,
            }
        )
    return pd.DataFrame(rows)


def choose_placements(
    campaign_types: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Sample placements from campaign-type-specific inventories."""

    result = np.empty(len(campaign_types), dtype=object)
    for campaign_type, (placements, probabilities) in PLACEMENTS_BY_TYPE.items():
        mask = campaign_types == campaign_type
        result[mask] = rng.choice(placements, size=int(mask.sum()), p=probabilities)
    return result


def choose_devices(
    preferences: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Use a customer's preferred device most of the time."""

    devices = np.array(["mobile", "desktop", "tablet"], dtype=object)
    result = preferences.copy().astype(object)
    switch = rng.random(len(preferences)) > 0.82
    result[switch] = rng.choice(devices, size=int(switch.sum()), p=[0.68, 0.26, 0.06])
    return result


def sample_dates_for_campaigns(
    campaign_indices: np.ndarray,
    campaigns: pd.DataFrame,
    all_dates: pd.DatetimeIndex,
    all_date_weights: np.ndarray,
    rng: np.random.Generator,
) -> pd.DatetimeIndex:
    """Sample only active campaign dates while preserving traffic seasonality."""

    sampled = np.empty(len(campaign_indices), dtype="datetime64[ns]")
    starts = campaigns["start_date"].to_numpy(dtype="datetime64[ns]")
    ends = campaigns["end_date"].to_numpy(dtype="datetime64[ns]")
    date_values = all_dates.to_numpy(dtype="datetime64[ns]")

    for campaign_idx in np.unique(campaign_indices):
        positions = np.flatnonzero(campaign_indices == campaign_idx)
        active = (date_values >= starts[campaign_idx]) & (date_values <= ends[campaign_idx])
        active_dates = date_values[active]
        weights = all_date_weights[active]
        weights = weights / weights.sum()
        sampled[positions] = rng.choice(active_dates, size=len(positions), p=weights)
    return pd.DatetimeIndex(sampled)


def timestamps_from_dates(
    dates: pd.DatetimeIndex, rng: np.random.Generator
) -> pd.DatetimeIndex:
    """Add shopping-hour and minute distributions to calendar dates."""

    hours = rng.choice(
        np.arange(24),
        size=len(dates),
        p=np.array(
            [
                0.010, 0.006, 0.004, 0.003, 0.003, 0.006,
                0.018, 0.033, 0.045, 0.052, 0.056, 0.058,
                0.061, 0.061, 0.059, 0.060, 0.065, 0.072,
                0.079, 0.080, 0.070, 0.052, 0.029, 0.018,
            ]
        ),
    )
    minutes = rng.integers(0, 60, len(dates))
    seconds = rng.integers(0, 60, len(dates))
    return (
        dates
        + pd.to_timedelta(hours, unit="h")
        + pd.to_timedelta(minutes, unit="m")
        + pd.to_timedelta(seconds, unit="s")
    )


def funnel_probabilities(
    campaign_types: np.ndarray,
    placements: np.ndarray,
    tiers: np.ndarray,
    devices: np.ndarray,
    loyalty: np.ndarray,
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate causal click, cart, and purchase probabilities."""

    type_ctr = pd.Series(campaign_types).map(
        {
            "Sponsored Product": 0.0062,
            "Sponsored Brand": 0.0050,
            "Display": 0.0032,
            "Video": 0.0038,
        }
    ).to_numpy()
    placement_ctr = pd.Series(placements).map(
        {
            "search_top": 1.24,
            "search_carousel": 1.05,
            "product_page": 0.92,
            "category_page": 0.82,
            "offsite_display": 0.70,
        }
    ).to_numpy()
    tier_lift = pd.Series(tiers).map(
        {"Enterprise": 1.12, "Mid-Market": 1.03, "SMB": 0.94}
    ).to_numpy()
    device_ctr = pd.Series(devices).map(
        {"mobile": 1.04, "desktop": 1.00, "tablet": 0.90}
    ).to_numpy()
    weekend = np.where(dates.dayofweek >= 5, 1.08, 1.0)
    ctr = np.clip(type_ctr * placement_ctr * tier_lift * device_ctr * weekend, 0.003, 0.008)

    type_cart = pd.Series(campaign_types).map(
        {
            "Sponsored Product": 0.145,
            "Sponsored Brand": 0.125,
            "Display": 0.100,
            "Video": 0.108,
        }
    ).to_numpy()
    placement_cart = pd.Series(placements).map(
        {
            "search_top": 1.10,
            "search_carousel": 1.05,
            "product_page": 1.08,
            "category_page": 0.91,
            "offsite_display": 0.80,
        }
    ).to_numpy()
    loyalty_lift = pd.Series(loyalty).map(
        {"Bronze": 0.88, "Silver": 1.00, "Gold": 1.13, "Platinum": 1.25}
    ).to_numpy()
    price_lift = np.clip((30 / np.maximum(prices, 3)) ** 0.12, 0.82, 1.18)
    cart_probability = np.clip(
        type_cart * placement_cart * loyalty_lift * price_lift, 0.10, 0.15
    )

    type_purchase = pd.Series(campaign_types).map(
        {
            "Sponsored Product": 0.38,
            "Sponsored Brand": 0.35,
            "Display": 0.31,
            "Video": 0.32,
        }
    ).to_numpy()
    loyalty_purchase = pd.Series(loyalty).map(
        {"Bronze": 0.90, "Silver": 1.00, "Gold": 1.10, "Platinum": 1.18}
    ).to_numpy()
    promo = promotion_label(dates)
    promo_lift = np.where(promo == "none", 1.0, 1.10)
    purchase_probability = np.clip(
        type_purchase * loyalty_purchase * promo_lift * price_lift, 0.30, 0.40
    )
    return ctr, cart_probability, purchase_probability


def event_costs(
    event_types: np.ndarray,
    campaign_types: np.ndarray,
    placements: np.ndarray,
    tiers: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Calculate CPM-derived impression cost and CPC click cost."""

    cpm = pd.Series(campaign_types).map(
        {
            "Sponsored Product": 0.80,
            "Sponsored Brand": 1.10,
            "Display": 1.45,
            "Video": 2.25,
        }
    ).to_numpy()
    placement_lift = pd.Series(placements).map(
        {
            "search_top": 1.35,
            "search_carousel": 1.12,
            "product_page": 1.00,
            "category_page": 0.90,
            "offsite_display": 0.78,
        }
    ).to_numpy()
    tier_lift = pd.Series(tiers).map(
        {"Enterprise": 1.10, "Mid-Market": 1.00, "SMB": 0.92}
    ).to_numpy()
    noise = rng.lognormal(mean=0, sigma=0.12, size=len(event_types))
    impression_cost = cpm * placement_lift * tier_lift * noise / 1000
    cpc = cpm * placement_lift * tier_lift * noise * 0.16
    return np.where(
        event_types == "impression",
        impression_cost,
        np.where(event_types == "click", cpc, 0.0),
    ).round(6)


def append_csv(frame: pd.DataFrame, path: Path, first_write: bool) -> None:
    """Append a frame with a header only on the first write."""

    frame.to_csv(path, mode="w" if first_write else "a", header=first_write, index=False)


def build_event_rows(
    impression_frame: pd.DataFrame,
    click_mask: np.ndarray,
    cart_mask: np.ndarray,
    purchase_mask: np.ndarray,
    next_event_id: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Expand sampled impressions into ordered funnel events.

    Returns all event rows, one record per clicked funnel for later journey
    construction, and the next unused numeric event identifier.
    """

    frames: list[pd.DataFrame] = []
    funnel_records: list[pd.DataFrame] = []
    impression_frame = impression_frame.copy()
    impression_frame["event_type"] = "impression"
    impression_frame["funnel_key"] = np.arange(len(impression_frame), dtype=np.int64)
    frames.append(impression_frame)

    clicked = impression_frame.loc[click_mask].copy()
    if not clicked.empty:
        clicked["event_timestamp"] += pd.to_timedelta(rng.integers(20, 900, len(clicked)), unit="s")
        clicked["event_type"] = "click"
        frames.append(clicked)

        clicked_funnel = clicked.copy()
        clicked_funnel["has_cart"] = cart_mask[click_mask]
        clicked_funnel["has_purchase"] = purchase_mask[click_mask]
        funnel_records.append(clicked_funnel)

    carted = impression_frame.loc[cart_mask].copy()
    if not carted.empty:
        carted["event_timestamp"] += pd.to_timedelta(rng.integers(2, 45, len(carted)), unit="m")
        carted["event_type"] = "add_to_cart"
        frames.append(carted)

    purchased = impression_frame.loc[purchase_mask].copy()
    if not purchased.empty:
        purchased["event_timestamp"] += pd.to_timedelta(rng.integers(8, 180, len(purchased)), unit="m")
        purchased["event_type"] = "purchase"
        frames.append(purchased)

    events = pd.concat(frames, ignore_index=True)
    events.sort_values(["funnel_key", "event_timestamp"], inplace=True, kind="stable")
    ids = np.arange(next_event_id, next_event_id + len(events), dtype=np.int64)
    events.insert(0, "event_id", [f"EVT{i:010d}" for i in ids])
    next_event_id += len(events)

    event_id_lookup = events[["funnel_key", "event_type", "event_id", "event_timestamp"]]
    funnels = (
        pd.concat(funnel_records, ignore_index=True)
        if funnel_records
        else pd.DataFrame()
    )
    if not funnels.empty:
        funnels = funnels.merge(
            event_id_lookup[event_id_lookup["event_type"] == "impression"].rename(
                columns={
                    "event_id": "impression_event_id",
                    "event_timestamp": "impression_timestamp",
                }
            )[["funnel_key", "impression_event_id", "impression_timestamp"]],
            on="funnel_key",
            how="left",
        )
        funnels = funnels.merge(
            event_id_lookup[event_id_lookup["event_type"] == "click"].rename(
                columns={"event_id": "click_event_id"}
            )[["funnel_key", "click_event_id"]],
            on="funnel_key",
            how="left",
        )
        cart_lookup = event_id_lookup[event_id_lookup["event_type"] == "add_to_cart"].rename(
            columns={
                "event_id": "cart_event_id",
                "event_timestamp": "cart_timestamp",
            }
        )
        funnels = funnels.merge(
            cart_lookup[["funnel_key", "cart_event_id", "cart_timestamp"]],
            on="funnel_key",
            how="left",
        )
        purchase_lookup = event_id_lookup[event_id_lookup["event_type"] == "purchase"].rename(
            columns={
                "event_id": "purchase_event_id",
                "event_timestamp": "purchase_timestamp",
            }
        )
        funnels = funnels.merge(
            purchase_lookup[["funnel_key", "purchase_event_id", "purchase_timestamp"]],
            on="funnel_key",
            how="left",
        )

    events.drop(columns=["funnel_key"], inplace=True)
    events["cost"] = event_costs(
        events["event_type"].to_numpy(),
        events["campaign_type"].to_numpy(),
        events["placement"].to_numpy(),
        events["advertiser_tier"].to_numpy(),
        rng,
    )
    output_columns = [
        "event_id",
        "campaign_id",
        "customer_id",
        "product_id",
        "event_timestamp",
        "event_type",
        "placement",
        "device_type",
        "cost",
    ]
    return events[output_columns], funnels, next_event_id


def generate_ad_events(
    config: GenerationConfig,
    advertisers: pd.DataFrame,
    products: pd.DataFrame,
    customers: pd.DataFrame,
    campaigns: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, float], int]:
    """Stream ad events to CSV and retain clicked funnels for paths/orders."""

    output_path = config.output_dir / "fact_ad_events.csv"
    all_dates = pd.date_range(START_DATE, END_DATE, freq="D")
    all_date_weights = date_volume_weights(all_dates)

    advertiser_tier = advertisers.set_index("advertiser_id")["tier"]
    campaign_work = campaigns.copy()
    campaign_work["advertiser_tier"] = campaign_work["advertiser_id"].map(advertiser_tier)
    campaign_weights = (
        campaign_work["daily_budget"].to_numpy()
        * campaign_work["advertiser_tier"].map(
            {"Enterprise": 1.12, "Mid-Market": 1.0, "SMB": 0.92}
        ).to_numpy()
    )
    campaign_weights = campaign_weights / campaign_weights.sum()

    product_groups = {
        advertiser_id: group.index.to_numpy()
        for advertiser_id, group in products.groupby("advertiser_id")
    }
    product_prices = products["base_price"].to_numpy()
    customer_preferences = customers["device_preference"].to_numpy()
    customer_loyalty = customers["loyalty_tier"].to_numpy()
    exposed_customer_count = max(
        1, int(len(customers) * (1 - ORGANIC_HOLDOUT_RATE))
    )

    # Downstream events add about 0.6%; reserve space to land near target_events.
    target_impressions = max(1, int(config.target_events / 1.0065))
    funnel_chunks: list[pd.DataFrame] = []
    next_event_id = 1
    total_rows = 0
    event_counts = {"impression": 0, "click": 0, "add_to_cart": 0, "purchase": 0}
    total_spend = 0.0
    first_write = True

    for offset in range(0, target_impressions, config.chunk_size):
        size = min(config.chunk_size, target_impressions - offset)
        campaign_idx = rng.choice(
            len(campaign_work), size=size, p=campaign_weights
        )
        campaign_rows = campaign_work.iloc[campaign_idx].reset_index(drop=True)
        dates = sample_dates_for_campaigns(
            campaign_idx, campaign_work, all_dates, all_date_weights, rng
        )
        timestamps = timestamps_from_dates(dates, rng)

        advertiser_ids = campaign_rows["advertiser_id"].to_numpy()
        product_idx = np.empty(size, dtype=np.int64)
        for advertiser_id in np.unique(advertiser_ids):
            positions = np.flatnonzero(advertiser_ids == advertiser_id)
            candidates = product_groups[advertiser_id]
            product_idx[positions] = rng.choice(candidates, size=len(positions))

        customer_idx = rng.integers(0, exposed_customer_count, size=size)
        campaign_types = campaign_rows["campaign_type"].to_numpy()
        placements = choose_placements(campaign_types, rng)
        devices = choose_devices(customer_preferences[customer_idx], rng)
        tiers = campaign_rows["advertiser_tier"].to_numpy()
        loyalty = customer_loyalty[customer_idx]
        prices = product_prices[product_idx]

        ctr, cart_probability, purchase_probability = funnel_probabilities(
            campaign_types, placements, tiers, devices, loyalty, prices, dates
        )
        click_mask = rng.random(size) < ctr
        cart_mask = click_mask & (rng.random(size) < cart_probability)
        purchase_mask = cart_mask & (rng.random(size) < purchase_probability)

        impression_frame = pd.DataFrame(
            {
                "campaign_id": campaign_rows["campaign_id"].to_numpy(),
                "customer_id": customers["customer_id"].to_numpy()[customer_idx],
                "product_id": products["product_id"].to_numpy()[product_idx],
                "event_timestamp": timestamps,
                "placement": placements,
                "device_type": devices,
                "campaign_type": campaign_types,
                "advertiser_tier": tiers,
                "base_price": prices,
            }
        )
        events, funnels, next_event_id = build_event_rows(
            impression_frame,
            click_mask,
            cart_mask,
            purchase_mask,
            next_event_id,
            rng,
        )
        append_csv(events, output_path, first_write)
        first_write = False
        total_rows += len(events)
        total_spend += float(events["cost"].sum())
        counts = events["event_type"].value_counts()
        for event_type in event_counts:
            event_counts[event_type] += int(counts.get(event_type, 0))
        if not funnels.empty:
            funnel_chunks.append(funnels)

        print(
            f"Generated {total_rows:,} ad events "
            f"({min(offset + size, target_impressions):,}/{target_impressions:,} impressions)",
            flush=True,
        )

    clicked_funnels = (
        pd.concat(funnel_chunks, ignore_index=True)
        if funnel_chunks
        else pd.DataFrame()
    )
    metrics = {
        "ad_event_rows": total_rows,
        "ad_spend": total_spend,
        **{f"{key}_rows": value for key, value in event_counts.items()},
    }
    return clicked_funnels, metrics, next_event_id


def generate_assist_events(
    clicked_funnels: pd.DataFrame,
    campaigns: pd.DataFrame,
    next_event_id: int,
    output_path: Path,
    event_metrics: dict[str, float],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Append genuine pre-conversion assist events and attach them to funnels."""

    clicked_funnels = clicked_funnels.copy()
    clicked_funnels["assist_touchpoints"] = [[] for _ in range(len(clicked_funnels))]
    if clicked_funnels.empty:
        return clicked_funnels, event_metrics

    campaign_lookup = campaigns.set_index("campaign_id")
    advertiser_campaigns = {
        advertiser_id: group["campaign_id"].tolist()
        for advertiser_id, group in campaigns.groupby("advertiser_id")
    }
    assist_rows: list[dict[str, object]] = []

    for row_index, row in clicked_funnels[clicked_funnels["has_purchase"]].iterrows():
        campaign = campaign_lookup.loc[row["campaign_id"]]
        purchase_time = pd.Timestamp(row["purchase_timestamp"])
        window_start = purchase_time - pd.Timedelta(days=LOOKBACK_DAYS)
        candidates: list[str] = []
        for campaign_id in advertiser_campaigns[campaign["advertiser_id"]]:
            candidate = campaign_lookup.loc[campaign_id]
            if (
                pd.Timestamp(candidate["start_date"]) < purchase_time
                and pd.Timestamp(candidate["end_date"]) >= window_start
            ):
                candidates.append(campaign_id)
        if not candidates:
            candidates = [row["campaign_id"]]

        assist_count = int(rng.choice([1, 2, 3, 4], p=[0.30, 0.38, 0.22, 0.10]))
        funnel_assists: list[dict[str, str]] = []
        for _ in range(assist_count):
            assist_campaign_id = str(rng.choice(candidates))
            assist_campaign = campaign_lookup.loc[assist_campaign_id]
            earliest = max(
                window_start,
                pd.Timestamp(assist_campaign["start_date"]),
            )
            latest = min(
                purchase_time - pd.Timedelta(hours=1),
                pd.Timestamp(assist_campaign["end_date"]) + pd.Timedelta(days=1)
                - pd.Timedelta(seconds=1),
            )
            if earliest >= latest:
                assist_campaign_id = str(row["campaign_id"])
                assist_campaign = campaign
                earliest = max(window_start, pd.Timestamp(campaign["start_date"]))
                latest = purchase_time - pd.Timedelta(hours=1)

            span_seconds = max(1, int((latest - earliest).total_seconds()))
            assist_time = earliest + pd.Timedelta(
                seconds=int(rng.integers(0, span_seconds))
            )
            assist_placement = str(
                rng.choice(PLACEMENTS_BY_TYPE[assist_campaign["campaign_type"]][0])
            )
            assist_event_type = str(
                rng.choice(["impression", "click"], p=[0.62, 0.38])
            )
            event_id = f"EVT{next_event_id:010d}"
            next_event_id += 1
            assist_rows.append(
                {
                    "event_id": event_id,
                    "campaign_id": assist_campaign_id,
                    "customer_id": row["customer_id"],
                    "product_id": row["product_id"],
                    "event_timestamp": assist_time,
                    "event_type": assist_event_type,
                    "placement": assist_placement,
                    "device_type": row["device_type"],
                    "campaign_type": assist_campaign["campaign_type"],
                    "advertiser_tier": row["advertiser_tier"],
                }
            )
            funnel_assists.append(
                touchpoint(
                    assist_time,
                    assist_campaign_id,
                    assist_campaign["campaign_type"],
                    assist_placement,
                    assist_event_type,
                    event_id,
                )
            )
        clicked_funnels.at[row_index, "assist_touchpoints"] = funnel_assists

    if assist_rows:
        assists = pd.DataFrame(assist_rows)
        assists["cost"] = event_costs(
            assists["event_type"].to_numpy(),
            assists["campaign_type"].to_numpy(),
            assists["placement"].to_numpy(),
            assists["advertiser_tier"].to_numpy(),
            rng,
        )
        output_columns = [
            "event_id", "campaign_id", "customer_id", "product_id",
            "event_timestamp", "event_type", "placement", "device_type", "cost",
        ]
        append_csv(assists[output_columns], output_path, first_write=False)
        counts = assists["event_type"].value_counts()
        event_metrics["ad_event_rows"] += len(assists)
        event_metrics["ad_spend"] += float(assists["cost"].sum())
        event_metrics["impression_rows"] += int(counts.get("impression", 0))
        event_metrics["click_rows"] += int(counts.get("click", 0))

    return clicked_funnels, event_metrics


def price_for_order(
    base_price: float, timestamp: pd.Timestamp, rng: np.random.Generator
) -> float:
    """Apply modest regular discounts and deeper promotion discounts."""

    promo = promotion_label(pd.DatetimeIndex([timestamp]))[0]
    if promo != "none":
        discount = float(rng.uniform(0.10, 0.25))
    else:
        discount = float(rng.choice([0.0, rng.uniform(0.03, 0.12)], p=[0.72, 0.28]))
    return round(base_price * (1 - discount), 2)


def generate_orders(
    clicked_funnels: pd.DataFrame,
    products: pd.DataFrame,
    customers: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Create one paid order per purchase event plus independent organic demand."""

    product_lookup = products.set_index("product_id")
    order_rows: list[dict[str, object]] = []
    purchase_to_order: dict[str, str] = {}
    purchase_funnels = (
        clicked_funnels[clicked_funnels["has_purchase"]].copy()
        if not clicked_funnels.empty
        else pd.DataFrame()
    )

    next_order = 1
    for row in purchase_funnels.itertuples(index=False):
        product = product_lookup.loc[row.product_id]
        quantity = int(rng.choice([1, 2, 3, 4], p=[0.72, 0.20, 0.06, 0.02]))
        unit_price = price_for_order(float(product["base_price"]), row.purchase_timestamp, rng)
        order_id = f"ORD{next_order:09d}"
        order_rows.append(
            {
                "order_id": order_id,
                "customer_id": row.customer_id,
                "order_timestamp": row.purchase_timestamp,
                "product_id": row.product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "order_total": round(quantity * unit_price, 2),
                "is_organic": False,
                "purchase_event_id": row.purchase_event_id,
            }
        )
        purchase_to_order[str(row.purchase_event_id)] = order_id
        next_order += 1

    days = (END_DATE - START_DATE).days + 1
    expected_organic = len(customers) * days * 0.00045
    organic_count = int(rng.poisson(expected_organic))
    holdout_start = max(0, int(len(customers) * (1 - ORGANIC_HOLDOUT_RATE)))
    organic_customer_idx = rng.integers(holdout_start, len(customers), organic_count)
    organic_product_idx = rng.choice(
        len(products),
        organic_count,
        p=(
            1 / np.sqrt(products["base_price"].to_numpy())
            / (1 / np.sqrt(products["base_price"].to_numpy())).sum()
        ),
    )
    organic_dates = pd.DatetimeIndex(
        rng.choice(
            pd.date_range(START_DATE, END_DATE, freq="D"),
            size=organic_count,
            p=date_volume_weights(pd.date_range(START_DATE, END_DATE, freq="D")),
        )
    )
    organic_timestamps = timestamps_from_dates(organic_dates, rng)

    for customer_idx, product_idx, timestamp in zip(
        organic_customer_idx, organic_product_idx, organic_timestamps
    ):
        product = products.iloc[int(product_idx)]
        quantity = int(rng.choice([1, 2, 3, 4], p=[0.76, 0.18, 0.05, 0.01]))
        unit_price = price_for_order(float(product["base_price"]), timestamp, rng)
        order_rows.append(
            {
                "order_id": f"ORD{next_order:09d}",
                "customer_id": customers.iloc[int(customer_idx)]["customer_id"],
                "order_timestamp": timestamp,
                "product_id": product["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "order_total": round(quantity * unit_price, 2),
                "is_organic": True,
                "purchase_event_id": "",
            }
        )
        next_order += 1

    orders = pd.DataFrame(order_rows)
    if not orders.empty:
        orders.sort_values(["order_timestamp", "order_id"], inplace=True)
    return orders, purchase_to_order


def touchpoint(
    timestamp: pd.Timestamp,
    campaign_id: str,
    campaign_type: str,
    placement: str,
    event_type: str,
    event_id: str,
) -> dict[str, str]:
    """Return a JSON-serializable attribution touchpoint."""

    return {
        "timestamp": pd.Timestamp(timestamp).isoformat(),
        "campaign_id": campaign_id,
        "campaign_type": campaign_type,
        "placement": placement,
        "event_type": event_type,
        "event_id": event_id,
    }


def generate_customer_journeys(
    clicked_funnels: pd.DataFrame,
    campaigns: pd.DataFrame,
    purchase_to_order: dict[str, str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Build click-qualified 14-day paths with multi-touch conversion assists."""

    if clicked_funnels.empty:
        return pd.DataFrame(
            columns=[
                "path_id", "customer_id", "product_id", "path_start_timestamp",
                "path_end_timestamp", "ordered_touchpoints", "touchpoint_count",
                "conversion_flag", "order_id", "lookback_days",
            ]
        )

    campaign_lookup = campaigns.set_index("campaign_id")
    rows: list[dict[str, object]] = []

    for path_number, row in enumerate(clicked_funnels.itertuples(index=False), start=1):
        campaign = campaign_lookup.loc[row.campaign_id]
        base_touchpoints = [
            touchpoint(
                row.impression_timestamp,
                row.campaign_id,
                campaign["campaign_type"],
                row.placement,
                "impression",
                row.impression_event_id,
            ),
            touchpoint(
                row.event_timestamp,
                row.campaign_id,
                campaign["campaign_type"],
                row.placement,
                "click",
                row.click_event_id,
            ),
        ]
        if row.has_cart:
            base_touchpoints.append(
                touchpoint(
                    row.cart_timestamp,
                    row.campaign_id,
                    campaign["campaign_type"],
                    row.placement,
                    "add_to_cart",
                    row.cart_event_id,
                )
            )

        conversion = bool(row.has_purchase)
        if conversion:
            base_touchpoints.extend(row.assist_touchpoints)
            base_touchpoints.append(
                touchpoint(
                    row.purchase_timestamp,
                    row.campaign_id,
                    campaign["campaign_type"],
                    row.placement,
                    "purchase",
                    row.purchase_event_id,
                )
            )
            path_end = row.purchase_timestamp
            order_id = purchase_to_order.get(str(row.purchase_event_id), "")
        else:
            path_end = min(
                pd.Timestamp(row.event_timestamp) + pd.Timedelta(days=LOOKBACK_DAYS),
                END_DATE + pd.Timedelta(days=1) - pd.Timedelta(seconds=1),
            )
            order_id = ""

        base_touchpoints.sort(key=lambda item: item["timestamp"])
        path_start = pd.Timestamp(base_touchpoints[0]["timestamp"])
        rows.append(
            {
                "path_id": f"PTH{path_number:09d}",
                "customer_id": row.customer_id,
                "product_id": row.product_id,
                "path_start_timestamp": path_start,
                "path_end_timestamp": path_end,
                "ordered_touchpoints": json.dumps(base_touchpoints, separators=(",", ":")),
                "touchpoint_count": len(base_touchpoints),
                "conversion_flag": conversion,
                "order_id": order_id,
                "lookback_days": LOOKBACK_DAYS,
            }
        )
    return pd.DataFrame(rows)


def write_dimensions(
    output_dir: Path,
    advertisers: pd.DataFrame,
    products: pd.DataFrame,
    customers: pd.DataFrame,
    campaigns: pd.DataFrame,
) -> None:
    """Write all dimension tables."""

    tables = {
        "dim_advertisers.csv": advertisers,
        "dim_products.csv": products,
        "dim_customers.csv": customers,
        "dim_campaigns.csv": campaigns,
    }
    for filename, frame in tables.items():
        frame.to_csv(output_dir / filename, index=False)


def prepare_output_directory(config: GenerationConfig) -> None:
    """Create an empty output directory without silently deleting data."""

    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        if not config.overwrite:
            raise FileExistsError(
                f"{config.output_dir} is not empty. Use --overwrite to replace generated CSVs."
            )
        for csv_path in config.output_dir.glob("*.csv"):
            csv_path.unlink()
    config.output_dir.mkdir(parents=True, exist_ok=True)


def print_summary(
    dimensions: Iterable[tuple[str, pd.DataFrame]],
    event_metrics: dict[str, float],
    orders: pd.DataFrame,
    journeys: pd.DataFrame,
) -> None:
    """Print immediate data-quality and business sanity checks."""

    paid_orders = orders[~orders["is_organic"]] if not orders.empty else orders
    paid_revenue = float(paid_orders["order_total"].sum()) if not paid_orders.empty else 0.0
    spend = float(event_metrics["ad_spend"])
    clicks = int(event_metrics["click_rows"])
    impressions = int(event_metrics["impression_rows"])
    purchases = int(event_metrics["purchase_rows"])
    conversion_rate = purchases / clicks if clicks else 0.0
    ctr = clicks / impressions if impressions else 0.0
    average_acos = spend / paid_revenue if paid_revenue else math.nan

    print("\n=== Generation summary ===")
    for name, frame in dimensions:
        print(f"{name:26s} {len(frame):>12,} rows")
    print(f"{'fact_ad_events':26s} {int(event_metrics['ad_event_rows']):>12,} rows")
    print(f"{'fact_orders':26s} {len(orders):>12,} rows")
    print(f"{'fact_customer_journey':26s} {len(journeys):>12,} rows")
    print("\n=== Funnel sanity checks ===")
    print(f"CTR:                         {ctr:.3%}")
    print(f"Click-to-purchase rate:      {conversion_rate:.3%}")
    print(f"Attributed conversion rate: {purchases / impressions:.4%}")
    print(f"Average ACOS:                {average_acos:.2%}")
    print(f"Ad spend:                    ${spend:,.2f}")
    print(f"Attributed revenue:          ${paid_revenue:,.2f}")
    if not orders.empty:
        print(f"Organic order share:         {orders['is_organic'].mean():.2%}")


def generate_all(config: GenerationConfig) -> dict[str, pd.DataFrame | dict[str, float]]:
    """Run the complete deterministic generation pipeline."""

    prepare_output_directory(config)
    rng, fake = seeded_rng(config.seed)

    advertisers = generate_advertisers(config.advertisers, rng, fake)
    products = generate_products(config.products, advertisers, rng)
    customers = generate_customers(config.customers, rng)
    campaigns = generate_campaigns(config.campaigns, advertisers, rng)
    write_dimensions(config.output_dir, advertisers, products, customers, campaigns)

    clicked_funnels, event_metrics, next_event_id = generate_ad_events(
        config, advertisers, products, customers, campaigns, rng
    )
    clicked_funnels, event_metrics = generate_assist_events(
        clicked_funnels,
        campaigns,
        next_event_id,
        config.output_dir / "fact_ad_events.csv",
        event_metrics,
        rng,
    )
    orders, purchase_to_order = generate_orders(
        clicked_funnels, products, customers, rng
    )
    journeys = generate_customer_journeys(
        clicked_funnels, campaigns, purchase_to_order, rng
    )
    orders.to_csv(config.output_dir / "fact_orders.csv", index=False)
    journeys.to_csv(config.output_dir / "fact_customer_journey.csv", index=False)

    print_summary(
        [
            ("dim_advertisers", advertisers),
            ("dim_products", products),
            ("dim_customers", customers),
            ("dim_campaigns", campaigns),
        ],
        event_metrics,
        orders,
        journeys,
    )
    return {
        "advertisers": advertisers,
        "products": products,
        "customers": customers,
        "campaigns": campaigns,
        "orders": orders,
        "journeys": journeys,
        "event_metrics": event_metrics,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "raw",
        help="Directory for generated CSV files.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--target-events", type=int, default=DEFAULT_TARGET_EVENTS)
    parser.add_argument("--advertisers", type=int, default=50)
    parser.add_argument("--products", type=int, default=500)
    parser.add_argument("--customers", type=int, default=50_000)
    parser.add_argument("--campaigns", type=int, default=300)
    parser.add_argument("--chunk-size", type=int, default=250_000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""

    args = parse_args()
    config = GenerationConfig(
        output_dir=args.output_dir.resolve(),
        seed=args.seed,
        target_events=args.target_events,
        advertisers=args.advertisers,
        products=args.products,
        customers=args.customers,
        campaigns=args.campaigns,
        chunk_size=args.chunk_size,
        overwrite=args.overwrite,
    )
    generate_all(config)


if __name__ == "__main__":
    main()
