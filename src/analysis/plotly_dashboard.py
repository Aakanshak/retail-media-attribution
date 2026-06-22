"""Generate standalone Plotly analytics from the PostgreSQL warehouse.

Every dataset is queried through SQLAlchemy. No dashboard reads the raw CSVs,
which keeps the visual layer connected to the same validated database tables
used by SQL analysis and downstream BI.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv
from plotly.subplots import make_subplots
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL

from src.attribution.common import Journey
from src.attribution.model_comparison import comparison_table


LOGGER = logging.getLogger("plotly_dashboard")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROMOTION_WINDOWS = (
    ("2024-08-05", "2024-09-08", "Back-to-School"),
    ("2024-11-18", "2024-12-31", "Holiday"),
)

ATTRIBUTION_MODELS = ("Last Touch", "Linear", "Markov", "Shapley")

FUNNEL_SQL = """
SELECT
    c.campaign_type,
    e.event_type,
    count(*) AS event_count
FROM fact_ad_events AS e
INNER JOIN dim_campaigns AS c
    ON c.campaign_id = e.campaign_id
GROUP BY c.campaign_type, e.event_type;
"""

DAILY_ECONOMICS_SQL = """
WITH daily_spend AS (
    SELECT
        event_timestamp::date AS activity_date,
        sum(cost) AS spend
    FROM fact_ad_events
    GROUP BY event_timestamp::date
),
daily_revenue AS (
    SELECT
        order_timestamp::date AS activity_date,
        sum(order_total) AS revenue
    FROM fact_orders
    GROUP BY order_timestamp::date
),
date_bounds AS (
    SELECT
        least(min_spend_date, min_revenue_date) AS min_date,
        greatest(max_spend_date, max_revenue_date) AS max_date
    FROM (
        SELECT
            min(activity_date) AS min_spend_date,
            max(activity_date) AS max_spend_date
        FROM daily_spend
    ) AS spend_bounds
    CROSS JOIN (
        SELECT
            min(activity_date) AS min_revenue_date,
            max(activity_date) AS max_revenue_date
        FROM daily_revenue
    ) AS revenue_bounds
),
calendar AS (
    SELECT generate_series(min_date, max_date, interval '1 day')::date AS activity_date
    FROM date_bounds
)
SELECT
    calendar.activity_date,
    coalesce(daily_spend.spend, 0) AS spend,
    coalesce(daily_revenue.revenue, 0) AS revenue
FROM calendar
LEFT JOIN daily_spend USING (activity_date)
LEFT JOIN daily_revenue USING (activity_date)
ORDER BY calendar.activity_date;
"""

ATTRIBUTION_JOURNEYS_SQL = """
SELECT
    j.path_id,
    j.ordered_touchpoints::text AS ordered_touchpoints,
    j.conversion_flag,
    j.order_id,
    coalesce(o.order_total, 0) AS revenue
FROM fact_customer_journey AS j
LEFT JOIN fact_orders AS o
    ON o.order_id = j.order_id;
"""

CHANNEL_SPEND_SQL = """
SELECT
    c.campaign_type || ' | ' || e.placement AS channel,
    sum(e.cost) AS spend
FROM fact_ad_events AS e
INNER JOIN dim_campaigns AS c
    ON c.campaign_id = e.campaign_id
GROUP BY c.campaign_type, e.placement
ORDER BY channel;
"""

BUDGET_CONTROL_SQL = """
WITH dataset_boundary AS (
    SELECT max(event_timestamp)::date AS max_event_date
    FROM fact_ad_events
),
campaign_calendar AS (
    SELECT
        c.campaign_id,
        c.campaign_name,
        c.daily_budget,
        calendar_date::date AS spend_date
    FROM dim_campaigns AS c
    CROSS JOIN dataset_boundary AS b
    CROSS JOIN LATERAL generate_series(
        c.start_date,
        least(c.end_date, b.max_event_date),
        interval '1 day'
    ) AS calendar_date
),
daily_spend AS (
    SELECT
        campaign_id,
        event_timestamp::date AS spend_date,
        sum(cost) AS spend
    FROM fact_ad_events
    GROUP BY campaign_id, event_timestamp::date
),
complete_daily AS (
    SELECT
        cc.campaign_id,
        cc.campaign_name,
        cc.daily_budget,
        cc.spend_date,
        coalesce(ds.spend, 0) AS spend
    FROM campaign_calendar AS cc
    LEFT JOIN daily_spend AS ds
        ON ds.campaign_id = cc.campaign_id
       AND ds.spend_date = cc.spend_date
),
rolling AS (
    SELECT
        *,
        avg(spend) OVER (
            PARTITION BY campaign_id
            ORDER BY spend_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS rolling_7d_avg_spend
    FROM complete_daily
),
classified AS (
    SELECT
        *,
        rolling_7d_avg_spend / NULLIF(daily_budget, 0) AS pacing_ratio,
        CASE
            WHEN rolling_7d_avg_spend / NULLIF(daily_budget, 0) >= 1.50
              OR rolling_7d_avg_spend / NULLIF(daily_budget, 0) <= 0.50
                THEN 'Critical'
            WHEN rolling_7d_avg_spend / NULLIF(daily_budget, 0) >= 1.20
              OR rolling_7d_avg_spend / NULLIF(daily_budget, 0) <= 0.80
                THEN 'Warning'
            ELSE 'On-Track'
        END AS severity
    FROM rolling
),
latest_status AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY campaign_id
            ORDER BY spend_date DESC
        ) AS recency_rank
    FROM classified
),
selected_campaign AS (
    SELECT campaign_id
    FROM latest_status
    WHERE recency_rank = 1
      AND (
          CAST(:campaign_id AS varchar) IS NULL
          OR campaign_id = CAST(:campaign_id AS varchar)
      )
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'Warning' THEN 2 ELSE 3 END,
        abs(pacing_ratio - 1) DESC,
        campaign_id
    LIMIT 1
)
SELECT
    c.campaign_id,
    c.campaign_name,
    c.spend_date,
    c.spend,
    c.daily_budget,
    c.rolling_7d_avg_spend,
    c.pacing_ratio,
    c.severity
FROM classified AS c
INNER JOIN selected_campaign AS s USING (campaign_id)
ORDER BY c.spend_date;
"""


@dataclass(frozen=True)
class DashboardData:
    """All database-backed datasets needed by the six charts."""

    funnel: pd.DataFrame
    daily_economics: pd.DataFrame
    attribution: pd.DataFrame
    cohorts: pd.DataFrame
    rfm: pd.DataFrame
    budget_pacing: pd.DataFrame


def create_postgres_engine(env_file: Path | None = None) -> Engine:
    """Create a SQLAlchemy 2.x engine using `.env` PostgreSQL credentials."""

    load_dotenv(env_file or PROJECT_ROOT / ".env")
    required = (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL environment variables: {', '.join(missing)}"
        )
    url = URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        database=os.environ["POSTGRES_DB"],
        query={"sslmode": os.getenv("POSTGRES_SSLMODE", "prefer")},
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10"))
        },
    )


def query_dataframe(
    engine: Engine,
    statement: str,
    params: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Execute SQL through SQLAlchemy and return a DataFrame."""

    with engine.connect() as connection:
        return pd.read_sql_query(text(statement), connection, params=params)


def read_sql_file(path: Path) -> str:
    """Read a documented analytical SQL file."""

    return path.read_text(encoding="utf-8")


def load_attribution_comparison(engine: Engine) -> pd.DataFrame:
    """Query journeys/spend from PostgreSQL and run four attribution models."""

    journey_rows = query_dataframe(engine, ATTRIBUTION_JOURNEYS_SQL)
    journeys = [
        Journey(
            path_id=str(row.path_id),
            touchpoints=tuple(
                json.loads(row.ordered_touchpoints)
                if isinstance(row.ordered_touchpoints, str)
                else row.ordered_touchpoints
            ),
            converted=bool(row.conversion_flag),
            order_id=None if pd.isna(row.order_id) else str(row.order_id),
            revenue=float(row.revenue),
        )
        for row in journey_rows.itertuples(index=False)
    ]
    spend = query_dataframe(engine, CHANNEL_SPEND_SQL)
    long_table, _ = comparison_table(
        journeys,
        spend,
        granularity="campaign_type_placement",
        shapley_max_channels=8,
    )
    return long_table[long_table["model"].isin(ATTRIBUTION_MODELS)].copy()


def load_dashboard_data(
    engine: Engine,
    campaign_id: str | None = None,
) -> DashboardData:
    """Load all six chart datasets directly from PostgreSQL."""

    query_dir = PROJECT_ROOT / "sql" / "queries"
    LOGGER.info("Querying funnel")
    funnel = query_dataframe(engine, FUNNEL_SQL)
    LOGGER.info("Querying daily spend and revenue")
    daily_economics = query_dataframe(engine, DAILY_ECONOMICS_SQL)
    LOGGER.info("Running attribution comparison from database journeys")
    attribution = load_attribution_comparison(engine)
    LOGGER.info("Querying cohort retention")
    cohorts = query_dataframe(
        engine, read_sql_file(query_dir / "cohort_retention.sql")
    )
    LOGGER.info("Querying RFM segmentation")
    rfm = query_dataframe(engine, read_sql_file(query_dir / "rfm_segmentation.sql"))
    LOGGER.info("Querying budget pacing history")
    budget_pacing = query_dataframe(
        engine,
        BUDGET_CONTROL_SQL,
        params={"campaign_id": campaign_id},
    )
    return DashboardData(
        funnel=funnel,
        daily_economics=daily_economics,
        attribution=attribution,
        cohorts=cohorts,
        rfm=rfm,
        budget_pacing=budget_pacing,
    )


def apply_standard_layout(figure: go.Figure, title: str) -> go.Figure:
    """Apply consistent portfolio-ready styling."""

    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 13},
        margin={"l": 70, "r": 70, "t": 90, "b": 70},
        hoverlabel={"namelength": -1},
    )
    return figure


def build_funnel_chart(funnel: pd.DataFrame) -> go.Figure:
    """Build campaign-type funnel traces with consistent stage ordering."""

    stages = ["impression", "click", "add_to_cart", "purchase"]
    labels = ["Impressions", "Clicks", "Cart Adds", "Purchases"]
    pivot = (
        funnel.pivot_table(
            index="campaign_type",
            columns="event_type",
            values="event_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=stages, fill_value=0)
        .sort_index()
    )
    figure = go.Figure()
    for campaign_type, row in pivot.iterrows():
        figure.add_trace(
            go.Funnel(
                name=campaign_type,
                y=labels,
                x=row.to_numpy(),
                textinfo="value+percent initial",
                hovertemplate=(
                    f"<b>{campaign_type}</b><br>"
                    "%{y}: %{x:,.0f}<br>"
                    "%{percentInitial:.2%} of impressions<extra></extra>"
                ),
            )
        )
    figure.update_layout(funnelmode="group", legend_title_text="Campaign type")
    return apply_standard_layout(
        figure, "Retail Media Funnel by Campaign Type"
    )


def build_daily_economics_chart(daily: pd.DataFrame) -> go.Figure:
    """Build dual-axis daily spend and revenue with promotion annotations."""

    frame = daily.copy()
    frame["activity_date"] = pd.to_datetime(frame["activity_date"])
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=frame["activity_date"],
            y=frame["spend"],
            name="Daily Spend",
            mode="lines",
            line={"color": "#E45756", "width": 2},
            hovertemplate="%{x|%b %d, %Y}<br>Spend: $%{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["activity_date"],
            y=frame["revenue"],
            name="Daily Revenue",
            mode="lines",
            line={"color": "#4C78A8", "width": 2},
            hovertemplate="%{x|%b %d, %Y}<br>Revenue: $%{y:,.2f}<extra></extra>",
        ),
        secondary_y=True,
    )
    for start, end, label in PROMOTION_WINDOWS:
        figure.add_vrect(
            x0=start,
            x1=end,
            fillcolor="#F2CF5B",
            opacity=0.18,
            line_width=0,
            annotation_text=label,
            annotation_position="top left",
        )
    figure.update_yaxes(title_text="Ad spend ($)", secondary_y=False)
    figure.update_yaxes(title_text="Order revenue ($)", secondary_y=True)
    figure.update_xaxes(title_text="Date")
    return apply_standard_layout(
        figure, "Daily Spend vs Revenue with Promotional Seasonality"
    )


def build_attribution_chart(attribution: pd.DataFrame) -> go.Figure:
    """Build the four-model grouped channel-credit comparison."""

    frame = attribution.copy()
    frame["credit_pct"] = 100 * frame["conversion_credit_share"]
    channel_order = (
        frame.groupby("channel")["attributed_conversions"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )
    colors = {
        "Last Touch": "#E45756",
        "Linear": "#72B7B2",
        "Markov": "#4C78A8",
        "Shapley": "#B279A2",
    }
    figure = go.Figure()
    for model in ATTRIBUTION_MODELS:
        model_data = (
            frame[frame["model"].eq(model)]
            .set_index("channel")
            .reindex(channel_order)
            .fillna(0)
        )
        figure.add_trace(
            go.Bar(
                name=model,
                x=channel_order,
                y=model_data["credit_pct"],
                marker_color=colors[model],
                customdata=np.column_stack(
                    [
                        model_data["attributed_conversions"],
                        model_data["attributed_roas"],
                    ]
                ),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    f"Model: {model}<br>"
                    "Credit: %{y:.2f}%<br>"
                    "Conversions: %{customdata[0]:,.1f}<br>"
                    "Attributed ROAS: %{customdata[1]:.2f}<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        barmode="group",
        legend_title_text="Attribution model",
    )
    figure.update_xaxes(title_text="Channel", tickangle=-35)
    figure.update_yaxes(title_text="Attributed conversion credit (%)")
    return apply_standard_layout(
        figure, "Attribution Model Comparison: Where Does Credit Move?"
    )


def build_cohort_heatmap(cohorts: pd.DataFrame) -> go.Figure:
    """Build a month 1-6 retention triangle heatmap."""

    retention_columns = [
        f"month_{month}_retention_pct" for month in range(1, 7)
    ]
    frame = cohorts.copy()
    frame["cohort_month"] = pd.to_datetime(frame["cohort_month"]).dt.strftime(
        "%Y-%m"
    )
    matrix = frame[retention_columns].astype(float).to_numpy()
    figure = go.Figure(
        go.Heatmap(
            x=[f"Month {month}" for month in range(1, 7)],
            y=frame["cohort_month"],
            z=matrix,
            text=np.vectorize(lambda value: f"{value:.1f}%")(matrix),
            texttemplate="%{text}",
            colorscale="Blues",
            colorbar={"title": "Retention %"},
            hovertemplate=(
                "Cohort: %{y}<br>Period: %{x}<br>"
                "Retention: %{z:.2f}%<extra></extra>"
            ),
        )
    )
    figure.update_xaxes(title_text="Months after signup")
    figure.update_yaxes(title_text="Signup cohort", autorange="reversed")
    return apply_standard_layout(figure, "Customer Cohort Retention")


def build_rfm_scatter(rfm: pd.DataFrame) -> go.Figure:
    """Build a WebGL customer-level RFM segment scatter."""

    frame = rfm.copy()
    monetary = frame["monetary_value"].astype(float).clip(lower=0)
    max_root = np.sqrt(monetary.max()) if monetary.max() > 0 else 1.0
    frame["marker_size"] = 6 + 28 * np.sqrt(monetary) / max_root
    colors = {
        "Champions": "#2E8B57",
        "Loyal": "#4C78A8",
        "At-Risk": "#F2A541",
        "Churned": "#E45756",
        "Developing": "#9D9D9D",
    }
    figure = go.Figure()
    for segment in ["Champions", "Loyal", "At-Risk", "Churned", "Developing"]:
        segment_data = frame[frame["customer_segment"].eq(segment)]
        if segment_data.empty:
            continue
        figure.add_trace(
            go.Scattergl(
                x=segment_data["recency_days"],
                y=segment_data["frequency"],
                mode="markers",
                name=segment,
                marker={
                    "size": segment_data["marker_size"],
                    "color": colors[segment],
                    "opacity": 0.58,
                    "line": {"width": 0},
                },
                customdata=np.column_stack(
                    [
                        segment_data["customer_id"],
                        segment_data["monetary_value"],
                        segment_data["rfm_code"],
                    ]
                ),
                hovertemplate=(
                    "Customer: %{customdata[0]}<br>"
                    "Recency: %{x} days<br>"
                    "Frequency: %{y}<br>"
                    "Monetary: $%{customdata[1]:,.2f}<br>"
                    "RFM: %{customdata[2]}<extra></extra>"
                ),
            )
        )
    figure.update_xaxes(title_text="Recency (days; lower is better)")
    figure.update_yaxes(title_text="Purchase frequency")
    figure.update_layout(legend_title_text="RFM segment")
    return apply_standard_layout(
        figure, "RFM Customer Segmentation"
    )


def build_budget_control_chart(pacing: pd.DataFrame) -> go.Figure:
    """Build actual-versus-budget control chart with red anomaly markers."""

    if pacing.empty:
        raise ValueError("budget pacing query returned no campaign history")
    frame = pacing.copy()
    frame["spend_date"] = pd.to_datetime(frame["spend_date"])
    campaign_name = str(frame.iloc[0]["campaign_name"])
    anomalies = frame[~frame["severity"].eq("On-Track")]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame["spend_date"],
            y=frame["spend"],
            name="Actual Daily Spend",
            mode="lines",
            line={"color": "#4C78A8", "width": 1.8},
            hovertemplate="%{x|%b %d, %Y}<br>Spend: $%{y:,.2f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["spend_date"],
            y=frame["daily_budget"],
            name="Daily Budget",
            mode="lines",
            line={"color": "#333333", "width": 2, "dash": "dash"},
            hovertemplate="%{x|%b %d, %Y}<br>Budget: $%{y:,.2f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["spend_date"],
            y=frame["rolling_7d_avg_spend"],
            name="7-Day Average Spend",
            mode="lines",
            line={"color": "#72B7B2", "width": 2.2},
            hovertemplate=(
                "%{x|%b %d, %Y}<br>7-day average: $%{y:,.2f}<extra></extra>"
            ),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=anomalies["spend_date"],
            y=anomalies["spend"],
            name="Pacing Anomaly",
            mode="markers",
            marker={
                "color": "#D62728",
                "size": 9,
                "symbol": "diamond",
                "line": {"color": "white", "width": 1},
            },
            customdata=np.column_stack(
                [anomalies["severity"], 100 * anomalies["pacing_ratio"]]
            ),
            hovertemplate=(
                "%{x|%b %d, %Y}<br>Spend: $%{y:,.2f}<br>"
                "Severity: %{customdata[0]}<br>"
                "Budget utilization: %{customdata[1]:.1f}%<extra></extra>"
            ),
        )
    )
    figure.update_xaxes(title_text="Date")
    figure.update_yaxes(title_text="Spend ($)")
    return apply_standard_layout(
        figure, f"Budget Pacing Control Chart: {campaign_name}"
    )


def build_all_figures(data: DashboardData) -> dict[str, go.Figure]:
    """Build all six requested interactive figures."""

    return {
        "01_campaign_funnel.html": build_funnel_chart(data.funnel),
        "02_daily_spend_vs_revenue.html": build_daily_economics_chart(
            data.daily_economics
        ),
        "03_attribution_model_comparison.html": build_attribution_chart(
            data.attribution
        ),
        "04_cohort_retention_heatmap.html": build_cohort_heatmap(data.cohorts),
        "05_rfm_segment_scatter.html": build_rfm_scatter(data.rfm),
        "06_budget_pacing_control_chart.html": build_budget_control_chart(
            data.budget_pacing
        ),
    }


def export_figures(
    figures: Mapping[str, go.Figure],
    output_dir: Path,
) -> list[Path]:
    """Write each chart as a self-contained standalone HTML file."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, figure in figures.items():
        output_path = output_dir / filename
        # Embedding Plotly.js makes every file viewable without internet access.
        figure.write_html(
            output_path,
            include_plotlyjs=True,
            full_html=True,
            config={"displaylogo": False, "responsive": True},
        )
        paths.append(output_path)
        LOGGER.info("Wrote %s", output_path)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "dashboards" / "plotly",
    )
    parser.add_argument(
        "--campaign-id",
        help="Optional campaign for the budget chart; defaults to worst latest anomaly.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = parse_args()
    engine = create_postgres_engine(args.env_file)
    try:
        data = load_dashboard_data(engine, campaign_id=args.campaign_id)
        export_figures(build_all_figures(data), args.output_dir.resolve())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
