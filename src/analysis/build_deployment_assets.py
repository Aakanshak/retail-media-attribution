"""Build compact, Git-trackable analytics assets for the Streamlit deployment."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "app_data"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def build_event_aggregates() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Stream the event fact into funnel, daily, campaign, and KPI aggregates."""

    campaigns = pd.read_csv(
        RAW_DIR / "dim_campaigns.csv",
        usecols=[
            "campaign_id",
            "campaign_name",
            "campaign_type",
            "daily_budget",
            "target_acos",
        ],
    )
    campaign_lookup = campaigns.set_index("campaign_id")
    funnel_counts: Counter[tuple[str, str]] = Counter()
    daily_spend: defaultdict[pd.Timestamp, float] = defaultdict(float)
    campaign_metrics: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {
            "impressions": 0,
            "clicks": 0,
            "cart_adds": 0,
            "purchases": 0,
            "spend": 0.0,
        }
    )
    event_counts: Counter[str] = Counter()
    total_spend = 0.0

    for chunk in pd.read_csv(
        RAW_DIR / "fact_ad_events.csv",
        usecols=[
            "campaign_id",
            "event_timestamp",
            "event_type",
            "placement",
            "cost",
        ],
        chunksize=500_000,
        parse_dates=["event_timestamp"],
    ):
        chunk["campaign_type"] = chunk["campaign_id"].map(
            campaign_lookup["campaign_type"]
        )
        event_counts.update(chunk["event_type"])
        total_spend += float(chunk["cost"].sum())

        grouped_funnel = chunk.groupby(
            ["campaign_type", "event_type"], observed=True
        ).size()
        for key, value in grouped_funnel.items():
            funnel_counts[(str(key[0]), str(key[1]))] += int(value)

        grouped_daily = chunk.groupby(chunk["event_timestamp"].dt.date)["cost"].sum()
        for date_value, value in grouped_daily.items():
            daily_spend[pd.Timestamp(date_value)] += float(value)

        for campaign_id, group in chunk.groupby("campaign_id", observed=True):
            counts = group["event_type"].value_counts()
            metric = campaign_metrics[str(campaign_id)]
            metric["impressions"] += int(counts.get("impression", 0))
            metric["clicks"] += int(counts.get("click", 0))
            metric["cart_adds"] += int(counts.get("add_to_cart", 0))
            metric["purchases"] += int(counts.get("purchase", 0))
            metric["spend"] += float(group["cost"].sum())

    funnel = pd.DataFrame(
        [
            {
                "campaign_type": campaign_type,
                "event_type": event_type,
                "event_count": count,
            }
            for (campaign_type, event_type), count in funnel_counts.items()
        ]
    )
    daily = pd.DataFrame(
        {"date": list(daily_spend), "spend": list(daily_spend.values())}
    ).sort_values("date")

    campaign_rows = []
    for campaign_id, metric in campaign_metrics.items():
        campaign = campaign_lookup.loc[campaign_id]
        campaign_rows.append(
            {
                "campaign_id": campaign_id,
                "campaign_name": campaign["campaign_name"],
                "campaign_type": campaign["campaign_type"],
                "daily_budget": campaign["daily_budget"],
                "target_acos": campaign["target_acos"],
                **metric,
                "ctr": metric["clicks"] / metric["impressions"]
                if metric["impressions"]
                else 0,
                "cvr": metric["purchases"] / metric["clicks"]
                if metric["clicks"]
                else 0,
                "cpc": metric["spend"] / metric["clicks"]
                if metric["clicks"]
                else 0,
            }
        )
    campaign_performance = pd.DataFrame(campaign_rows)
    kpis = {
        "ad_events": int(sum(event_counts.values())),
        "impressions": int(event_counts["impression"]),
        "clicks": int(event_counts["click"]),
        "cart_adds": int(event_counts["add_to_cart"]),
        "purchases": int(event_counts["purchase"]),
        "spend": total_spend,
        "ctr": event_counts["click"] / event_counts["impression"],
        "click_to_cart": event_counts["add_to_cart"] / event_counts["click"],
        "cart_to_purchase": event_counts["purchase"] / event_counts["add_to_cart"],
    }
    return funnel, daily, campaign_performance, kpis


def build_order_and_customer_assets(
    daily: pd.DataFrame,
    campaign_performance: pd.DataFrame,
    kpis: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Add revenue, RFM segments, cohorts, and campaign revenue allocation."""

    orders = pd.read_csv(
        RAW_DIR / "fact_orders.csv",
        parse_dates=["order_timestamp"],
    )
    customers = pd.read_csv(
        RAW_DIR / "dim_customers.csv",
        parse_dates=["signup_date"],
    )
    daily_revenue = (
        orders.groupby(orders["order_timestamp"].dt.normalize())["order_total"]
        .sum()
        .rename("revenue")
    )
    daily = (
        daily.set_index("date")
        .join(daily_revenue, how="outer")
        .fillna(0)
        .reset_index()
        .rename(columns={"index": "date"})
        .sort_values("date")
    )

    paid_orders = orders[~orders["is_organic"]].copy()
    purchase_event_chunks = []
    for chunk in pd.read_csv(
        RAW_DIR / "fact_ad_events.csv",
        usecols=["event_id", "campaign_id", "event_type"],
        chunksize=500_000,
    ):
        purchases = chunk[chunk["event_type"].eq("purchase")]
        if not purchases.empty:
            purchase_event_chunks.append(purchases)
    purchase_events = pd.concat(purchase_event_chunks, ignore_index=True)
    paid_revenue_by_campaign = (
        paid_orders.merge(
            purchase_events,
            left_on="purchase_event_id",
            right_on="event_id",
            how="left",
        )
        .groupby("campaign_id")["order_total"]
        .sum()
    )
    campaign_performance["revenue"] = campaign_performance["campaign_id"].map(
        paid_revenue_by_campaign
    ).fillna(0)
    campaign_performance["roas"] = np.where(
        campaign_performance["spend"] > 0,
        campaign_performance["revenue"] / campaign_performance["spend"],
        0,
    )
    campaign_performance["acos"] = np.where(
        campaign_performance["revenue"] > 0,
        campaign_performance["spend"] / campaign_performance["revenue"],
        np.nan,
    )

    analysis_date = orders["order_timestamp"].max().normalize() + pd.Timedelta(days=1)
    customer_orders = orders.groupby("customer_id").agg(
        last_order=("order_timestamp", "max"),
        frequency=("order_id", "nunique"),
        monetary=("order_total", "sum"),
    )
    rfm = customers[["customer_id", "loyalty_tier", "region"]].merge(
        customer_orders,
        left_on="customer_id",
        right_index=True,
        how="left",
    )
    rfm["frequency"] = rfm["frequency"].fillna(0).astype(int)
    rfm["monetary"] = rfm["monetary"].fillna(0)
    rfm["recency_days"] = (
        analysis_date - pd.to_datetime(rfm["last_order"])
    ).dt.days.fillna(9999).astype(int)
    rfm["recency_score"] = pd.qcut(
        rfm["recency_days"].rank(method="first", ascending=False),
        5,
        labels=[1, 2, 3, 4, 5],
    ).astype(int)
    rfm["frequency_score"] = pd.qcut(
        rfm["frequency"].rank(method="first"),
        5,
        labels=[1, 2, 3, 4, 5],
    ).astype(int)
    rfm["monetary_score"] = pd.qcut(
        rfm["monetary"].rank(method="first"),
        5,
        labels=[1, 2, 3, 4, 5],
    ).astype(int)
    rfm["segment"] = np.select(
        [
            (rfm["recency_score"] >= 4)
            & (rfm["frequency_score"] >= 4)
            & (rfm["monetary_score"] >= 4),
            (rfm["recency_score"] >= 3) & (rfm["frequency_score"] >= 4),
            (rfm["recency_score"] <= 2) & (rfm["frequency_score"] >= 3),
            (rfm["recency_score"] == 1) & (rfm["frequency_score"] <= 2),
        ],
        ["Champions", "Loyal", "At-Risk", "Churned"],
        default="Developing",
    )
    rfm_export = rfm[
        [
            "customer_id",
            "loyalty_tier",
            "region",
            "recency_days",
            "frequency",
            "monetary",
            "segment",
        ]
    ]

    customers["cohort_month"] = customers["signup_date"].dt.to_period("M")
    orders["purchase_month"] = orders["order_timestamp"].dt.to_period("M")
    customer_months = (
        orders[["customer_id", "purchase_month"]]
        .drop_duplicates()
        .merge(customers[["customer_id", "cohort_month"]], on="customer_id")
    )
    customer_months["month_number"] = (
        customer_months["purchase_month"].astype(int)
        - customer_months["cohort_month"].astype(int)
    )
    cohort_sizes = customers.groupby("cohort_month")["customer_id"].nunique()
    retained = (
        customer_months[customer_months["month_number"].between(1, 6)]
        .groupby(["cohort_month", "month_number"])["customer_id"]
        .nunique()
        .unstack(fill_value=0)
    )
    cohort = retained.div(cohort_sizes, axis=0).mul(100)
    cohort = cohort.reindex(columns=range(1, 7), fill_value=0)
    cohort.columns = [f"month_{month}" for month in cohort.columns]
    cohort = cohort.reset_index()
    cohort["cohort_month"] = cohort["cohort_month"].astype(str)
    cohort = cohort[cohort["cohort_month"].between("2024-01", "2024-12")]

    kpis.update(
        {
            "orders": int(len(orders)),
            "organic_order_share": float(orders["is_organic"].mean()),
            "attributed_revenue": float(paid_orders["order_total"].sum()),
            "total_revenue": float(orders["order_total"].sum()),
            "roas": float(paid_orders["order_total"].sum() / kpis["spend"]),
            "acos": float(kpis["spend"] / paid_orders["order_total"].sum()),
            "customers": int(len(customers)),
        }
    )
    return daily, campaign_performance, rfm_export, cohort, kpis


def build_budget_pacing(campaign_performance: pd.DataFrame) -> pd.DataFrame:
    """Create a control-chart series for the campaign with the largest spend."""

    top_campaign = campaign_performance.nlargest(1, "spend").iloc[0]
    campaign_id = top_campaign["campaign_id"]
    budget = float(top_campaign["daily_budget"])
    daily: defaultdict[pd.Timestamp, float] = defaultdict(float)
    for chunk in pd.read_csv(
        RAW_DIR / "fact_ad_events.csv",
        usecols=["campaign_id", "event_timestamp", "cost"],
        chunksize=500_000,
        parse_dates=["event_timestamp"],
    ):
        selected = chunk[chunk["campaign_id"].eq(campaign_id)]
        grouped = selected.groupby(selected["event_timestamp"].dt.normalize())[
            "cost"
        ].sum()
        for date_value, value in grouped.items():
            daily[pd.Timestamp(date_value)] += float(value)
    frame = pd.DataFrame(
        {"date": list(daily), "spend": list(daily.values())}
    ).sort_values("date")
    full_dates = pd.date_range(frame["date"].min(), frame["date"].max())
    frame = (
        frame.set_index("date")
        .reindex(full_dates, fill_value=0)
        .rename_axis("date")
        .reset_index()
    )
    frame["daily_budget"] = budget
    frame["rolling_7d"] = frame["spend"].rolling(7, min_periods=1).mean()
    frame["severity"] = np.select(
        [
            (frame["rolling_7d"] >= 1.5 * budget)
            | (frame["rolling_7d"] <= 0.5 * budget),
            (frame["rolling_7d"] >= 1.2 * budget)
            | (frame["rolling_7d"] <= 0.8 * budget),
        ],
        ["Critical", "Warning"],
        default="On-Track",
    )
    frame["campaign_id"] = campaign_id
    frame["campaign_name"] = top_campaign["campaign_name"]
    return frame


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    funnel, daily, campaign_performance, kpis = build_event_aggregates()
    daily, campaign_performance, rfm, cohort, kpis = build_order_and_customer_assets(
        daily, campaign_performance, kpis
    )
    budget = build_budget_pacing(campaign_performance)
    attribution = pd.read_csv(
        PROCESSED_DIR / "attribution_model_comparison_long.csv"
    )
    attribution_stage = pd.read_csv(
        PROCESSED_DIR / "attribution_model_comparison_by_stage.csv"
    )

    outputs = {
        "funnel_by_campaign_type.csv": funnel,
        "daily_economics.csv": daily,
        "campaign_performance.csv": campaign_performance.sort_values(
            "spend", ascending=False
        ),
        "rfm_customers.csv": rfm,
        "cohort_retention.csv": cohort,
        "budget_pacing.csv": budget,
        "attribution_comparison.csv": attribution,
        "attribution_by_stage.csv": attribution_stage,
    }
    for filename, frame in outputs.items():
        frame.to_csv(OUTPUT_DIR / filename, index=False)
        print(f"Wrote {filename}: {len(frame):,} rows")
    (OUTPUT_DIR / "kpis.json").write_text(
        json.dumps(kpis, indent=2),
        encoding="utf-8",
    )
    print("Wrote kpis.json")


if __name__ == "__main__":
    main()
