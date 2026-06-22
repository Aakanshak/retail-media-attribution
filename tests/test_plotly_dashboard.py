"""Chart-construction tests that do not require a live PostgreSQL server."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.analysis.plotly_dashboard import (
    ATTRIBUTION_MODELS,
    DashboardData,
    build_all_figures,
    export_figures,
)


def sample_dashboard_data() -> DashboardData:
    funnel = pd.DataFrame(
        [
            ("Sponsored Product", "impression", 10_000),
            ("Sponsored Product", "click", 70),
            ("Sponsored Product", "add_to_cart", 10),
            ("Sponsored Product", "purchase", 4),
            ("Video", "impression", 8_000),
            ("Video", "click", 30),
            ("Video", "add_to_cart", 4),
            ("Video", "purchase", 1),
        ],
        columns=["campaign_type", "event_type", "event_count"],
    )
    daily = pd.DataFrame(
        {
            "activity_date": pd.date_range("2024-08-01", periods=10),
            "spend": range(10, 20),
            "revenue": range(30, 40),
        }
    )
    attribution_rows = []
    for model in ATTRIBUTION_MODELS:
        for channel, credit in [
            ("Sponsored Product | search_top", 0.7),
            ("Video | offsite_display", 0.3),
        ]:
            attribution_rows.append(
                {
                    "model": model,
                    "channel": channel,
                    "attributed_conversions": 100 * credit,
                    "conversion_credit_share": credit,
                    "attributed_roas": 2.0,
                }
            )
    cohorts = pd.DataFrame(
        {
            "cohort_month": ["2024-01-01", "2024-02-01"],
            "cohort_size": [100, 120],
            **{
                f"month_{month}_retention_pct": [20 - month, 18 - month]
                for month in range(1, 7)
            },
        }
    )
    rfm = pd.DataFrame(
        {
            "customer_id": ["CUS0000001", "CUS0000002"],
            "recency_days": [10, 120],
            "frequency": [8, 1],
            "monetary_value": [500.0, 20.0],
            "rfm_code": ["555", "111"],
            "customer_segment": ["Champions", "Churned"],
        }
    )
    pacing = pd.DataFrame(
        {
            "campaign_id": ["CAM00001"] * 3,
            "campaign_name": ["Test Campaign"] * 3,
            "spend_date": pd.date_range("2025-01-01", periods=3),
            "spend": [90.0, 160.0, 95.0],
            "daily_budget": [100.0] * 3,
            "rolling_7d_avg_spend": [90.0, 125.0, 115.0],
            "pacing_ratio": [0.9, 1.25, 1.15],
            "severity": ["On-Track", "Warning", "On-Track"],
        }
    )
    return DashboardData(funnel, daily, pd.DataFrame(attribution_rows), cohorts, rfm, pacing)


def test_builds_and_exports_all_six_plotly_figures(tmp_path):
    figures = build_all_figures(sample_dashboard_data())
    exported = export_figures(figures, tmp_path)

    assert len(figures) == 6
    assert len(exported) == 6
    assert all(path.exists() and "<html" in path.read_text(encoding="utf-8") for path in exported)
    assert all(isinstance(figure, go.Figure) for figure in figures.values())
    assert len(figures["01_campaign_funnel.html"].data) == 2
    assert len(figures["03_attribution_model_comparison.html"].data) == 4
    assert figures["04_cohort_retention_heatmap.html"].data[0].type == "heatmap"
    assert figures["06_budget_pacing_control_chart.html"].data[-1].name == "Pacing Anomaly"
