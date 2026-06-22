"""Smoke and invariant tests for synthetic retail-media generation."""

from __future__ import annotations

import json

import pandas as pd

from src.data_generation.generate_data import GenerationConfig, generate_all


def test_small_generation_is_linked_and_statistically_valid(tmp_path):
    output_dir = tmp_path / "raw"
    result = generate_all(
        GenerationConfig(
            output_dir=output_dir,
            seed=42,
            target_events=120_000,
            advertisers=10,
            products=100,
            customers=2_000,
            campaigns=30,
            chunk_size=40_000,
        )
    )

    expected_files = {
        "dim_advertisers.csv",
        "dim_products.csv",
        "dim_customers.csv",
        "dim_campaigns.csv",
        "fact_ad_events.csv",
        "fact_orders.csv",
        "fact_customer_journey.csv",
    }
    assert expected_files == {path.name for path in output_dir.glob("*.csv")}

    events = pd.read_csv(output_dir / "fact_ad_events.csv")
    orders = result["orders"]
    journeys = result["journeys"]

    assert events["event_id"].is_unique
    assert set(events["event_type"]).issubset(
        {"impression", "click", "add_to_cart", "purchase"}
    )
    counts = events["event_type"].value_counts()
    assert counts["impression"] > counts["click"] > counts.get("add_to_cart", 0)
    assert counts.get("add_to_cart", 0) >= counts.get("purchase", 0)
    ctr = counts["click"] / counts["impression"]
    click_to_cart = counts["add_to_cart"] / counts["click"]
    cart_to_purchase = counts["purchase"] / counts["add_to_cart"]
    assert 0.003 <= ctr <= 0.008
    assert 0.10 <= click_to_cart <= 0.15
    # The generator clips row-level probabilities to 30-40%; a small smoke
    # sample needs modest binomial tolerance around those configured bounds.
    assert 0.28 <= cart_to_purchase <= 0.42

    paid = orders[~orders["is_organic"]]
    organic = orders[orders["is_organic"]]
    purchase_event_ids = set(events.loc[events["event_type"] == "purchase", "event_id"])
    assert set(paid["purchase_event_id"]) == purchase_event_ids
    assert set(organic["customer_id"]).isdisjoint(set(events["customer_id"]))

    if not journeys.empty:
        parsed = journeys["ordered_touchpoints"].map(json.loads)
        assert parsed.map(len).equals(journeys["touchpoint_count"])
        journey_event_ids = {
            touch["event_id"]
            for path in parsed
            for touch in path
        }
        assert journey_event_ids.issubset(set(events["event_id"]))
        assert journeys["lookback_days"].eq(14).all()
        assert journeys.loc[journeys["conversion_flag"], "order_id"].ne("").all()


def test_fixed_seed_reproduces_dimensions(tmp_path):
    common = dict(
        seed=77,
        target_events=20_000,
        advertisers=8,
        products=40,
        customers=200,
        campaigns=16,
        chunk_size=10_000,
    )
    first = generate_all(GenerationConfig(output_dir=tmp_path / "first", **common))
    second = generate_all(GenerationConfig(output_dir=tmp_path / "second", **common))

    for key in ["advertisers", "products", "customers", "campaigns"]:
        pd.testing.assert_frame_equal(first[key], second[key])
