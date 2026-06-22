"""Unit tests for ETL schema and row validation."""

from __future__ import annotations

import pandas as pd

from src.etl.load_to_postgres import TABLE_SPECS


def spec_for(table: str):
    return next(spec for spec in TABLE_SPECS if spec.table == table)


def test_event_validator_accepts_valid_row_and_rejects_bad_enum():
    spec = spec_for("fact_ad_events")
    frame = pd.DataFrame(
        [
            {
                "event_id": "EVT0000000001",
                "campaign_id": "CAM00001",
                "customer_id": "CUS0000001",
                "product_id": "PRD000001",
                "event_timestamp": "2024-01-01 12:00:00",
                "event_type": "impression",
                "placement": "search_top",
                "device_type": "mobile",
                "cost": "0.001000",
            },
            {
                "event_id": "EVT0000000002",
                "campaign_id": "CAM00001",
                "customer_id": "CUS0000001",
                "product_id": "PRD000001",
                "event_timestamp": "2024-01-01 12:01:00",
                "event_type": "view",
                "placement": "search_top",
                "device_type": "mobile",
                "cost": "0.001000",
            },
        ],
        dtype="string",
    )

    valid, rejected = spec.validator(frame)

    assert len(valid) == 1
    assert len(rejected) == 1
    assert rejected.iloc[0]["rejection_reason"] == "invalid event_type"


def test_order_validator_enforces_paid_purchase_lineage():
    spec = spec_for("fact_orders")
    frame = pd.DataFrame(
        [
            {
                "order_id": "ORD000000001",
                "customer_id": "CUS0000001",
                "order_timestamp": "2024-01-01 12:00:00",
                "product_id": "PRD000001",
                "quantity": "1",
                "unit_price": "9.99",
                "order_total": "9.99",
                "is_organic": "false",
                "purchase_event_id": "",
            }
        ],
        dtype="string",
    )

    valid, rejected = spec.validator(frame)

    assert valid.empty
    assert rejected.iloc[0]["rejection_reason"] == "paid order missing purchase_event_id"

