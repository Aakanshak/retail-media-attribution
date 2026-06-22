"""Public Streamlit portfolio app for the retail-media attribution platform."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "app_data"
GITHUB_URL = "https://github.com/Aakanshak/retail-media-attribution"
POWERBI_GUIDE = f"{GITHUB_URL}/blob/main/dashboards/powerbi/page_layout.md"

COLORS = {
    "Sponsored Product": "#2563EB",
    "Sponsored Brand": "#0F766E",
    "Display": "#7C3AED",
    "Video": "#F59E0B",
    "Last Touch": "#DC2626",
    "Linear": "#0891B2",
    "Markov": "#2563EB",
    "Shapley": "#7C3AED",
}


st.set_page_config(
    page_title="Retail Media Intelligence",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.8rem; padding-bottom: 3rem;}
    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, .05);
    }
    .hero {
        padding: 1.5rem 1.75rem;
        border-radius: 18px;
        background: linear-gradient(120deg, #0f172a, #1d4ed8);
        color: white;
        margin-bottom: 1.25rem;
    }
    .hero h1 {margin: 0; font-size: 2.2rem;}
    .hero p {margin: .55rem 0 0; color: #dbeafe; max-width: 900px;}
    .insight {
        border-left: 5px solid #7c3aed;
        background: #f5f3ff;
        padding: 1rem 1.1rem;
        border-radius: 0 12px 12px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_data() -> dict[str, object]:
    return {
        "kpis": json.loads((DATA / "kpis.json").read_text(encoding="utf-8")),
        "funnel": pd.read_csv(DATA / "funnel_by_campaign_type.csv"),
        "daily": pd.read_csv(DATA / "daily_economics.csv", parse_dates=["date"]),
        "campaigns": pd.read_csv(DATA / "campaign_performance.csv"),
        "rfm": pd.read_csv(DATA / "rfm_customers.csv"),
        "cohort": pd.read_csv(DATA / "cohort_retention.csv"),
        "budget": pd.read_csv(DATA / "budget_pacing.csv", parse_dates=["date"]),
        "attribution": pd.read_csv(DATA / "attribution_comparison.csv"),
        "attribution_stage": pd.read_csv(DATA / "attribution_by_stage.csv"),
    }


def funnel_figure(frame: pd.DataFrame, campaign_types: list[str]) -> go.Figure:
    stages = ["impression", "click", "add_to_cart", "purchase"]
    labels = ["Impressions", "Clicks", "Cart Adds", "Purchases"]
    selected = frame[frame["campaign_type"].isin(campaign_types)]
    pivot = selected.pivot_table(
        index="campaign_type",
        columns="event_type",
        values="event_count",
        aggfunc="sum",
        fill_value=0,
    ).reindex(columns=stages, fill_value=0)
    figure = go.Figure()
    for campaign_type, row in pivot.iterrows():
        figure.add_trace(
            go.Funnel(
                name=campaign_type,
                y=labels,
                x=row.values,
                marker={"color": COLORS.get(campaign_type)},
                textinfo="value+percent initial",
            )
        )
    figure.update_layout(
        funnelmode="group",
        template="plotly_white",
        height=470,
        margin=dict(l=30, r=30, t=35, b=20),
        legend_title="Campaign type",
    )
    return figure


def daily_figure(frame: pd.DataFrame) -> go.Figure:
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["spend"],
            name="Ad Spend",
            line={"color": "#DC2626", "width": 2},
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["revenue"],
            name="Revenue",
            line={"color": "#2563EB", "width": 2},
        ),
        secondary_y=True,
    )
    for start, end, name in [
        ("2024-08-05", "2024-09-08", "Back-to-School"),
        ("2024-11-18", "2024-12-31", "Holiday"),
    ]:
        figure.add_vrect(
            x0=start,
            x1=end,
            fillcolor="#FBBF24",
            opacity=0.14,
            line_width=0,
            annotation_text=name,
            annotation_position="top left",
        )
    figure.update_yaxes(title_text="Spend ($)", secondary_y=False)
    figure.update_yaxes(title_text="Revenue ($)", secondary_y=True)
    figure.update_layout(
        template="plotly_white",
        height=440,
        margin=dict(l=30, r=30, t=35, b=20),
        hovermode="x unified",
    )
    return figure


def attribution_figure(frame: pd.DataFrame, models: list[str]) -> go.Figure:
    selected = frame[frame["model"].isin(models)].copy()
    selected["credit_pct"] = 100 * selected["conversion_credit_share"]
    channel_order = (
        selected.groupby("channel")["attributed_conversions"]
        .sum()
        .sort_values(ascending=False)
        .index
    )
    figure = px.bar(
        selected,
        x="channel",
        y="credit_pct",
        color="model",
        barmode="group",
        category_orders={"channel": channel_order.tolist(), "model": models},
        color_discrete_map=COLORS,
        custom_data=["attributed_conversions", "attributed_roas", "funnel_stage"],
        labels={"credit_pct": "Conversion credit (%)", "channel": ""},
    )
    figure.update_traces(
        hovertemplate=(
            "<b>%{x}</b><br>Credit: %{y:.2f}%<br>"
            "Conversions: %{customdata[0]:,.1f}<br>"
            "Attributed ROAS: %{customdata[1]:.2f}<br>"
            "Stage: %{customdata[2]}<extra></extra>"
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=520,
        xaxis_tickangle=-35,
        margin=dict(l=30, r=30, t=35, b=130),
        legend_title="Model",
    )
    return figure


data = load_data()
kpis = data["kpis"]

st.markdown(
    """
    <div class="hero">
      <h1>Retail Media Intelligence & Attribution</h1>
      <p>End-to-end portfolio platform combining Python, PostgreSQL, multi-touch attribution,
      interactive Plotly analytics, Excel reporting, and a Power BI semantic-model handoff.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Project")
    st.link_button("GitHub Repository", GITHUB_URL, width="stretch")
    st.link_button("Power BI Build Spec", POWERBI_GUIDE, width="stretch")
    st.download_button(
        "Excel Export · Campaigns",
        data["campaigns"].to_csv(index=False).encode("utf-8"),
        file_name="campaign_performance_excel.csv",
        mime="text/csv",
        width="stretch",
    )
    st.download_button(
        "Excel Export · Attribution",
        data["attribution"].to_csv(index=False).encode("utf-8"),
        file_name="attribution_comparison_excel.csv",
        mime="text/csv",
        width="stretch",
    )
    st.caption("Synthetic portfolio data · Jan 2024–Jun 2025")

overview, attribution_tab, campaigns_tab, customers_tab, stack_tab = st.tabs(
    ["Executive Overview", "Attribution", "Campaigns", "Customers", "Project Stack"]
)

with overview:
    cols = st.columns(5)
    cols[0].metric("Ad Events", f"{kpis['ad_events']/1_000_000:.2f}M")
    cols[1].metric("Ad Spend", f"${kpis['spend']:,.0f}")
    cols[2].metric("Attributed Revenue", f"${kpis['attributed_revenue']:,.0f}")
    cols[3].metric("ROAS", f"{kpis['roas']:.2f}x")
    cols[4].metric("ACOS", f"{kpis['acos']:.1%}")

    campaign_options = sorted(data["funnel"]["campaign_type"].unique())
    selected_campaign_types = st.multiselect(
        "Campaign types",
        campaign_options,
        default=campaign_options,
    )
    left, right = st.columns([1, 1.35])
    with left:
        st.subheader("Conversion Funnel")
        st.plotly_chart(
            funnel_figure(data["funnel"], selected_campaign_types),
            width="stretch",
        )
    with right:
        st.subheader("Daily Spend vs Revenue")
        st.plotly_chart(daily_figure(data["daily"]), width="stretch")

    st.markdown(
        f"""
        <div class="insight"><b>Measured funnel:</b> {kpis['ctr']:.3%} CTR,
        {kpis['click_to_cart']:.1%} click-to-cart, and
        {kpis['cart_to_purchase']:.1%} cart-to-purchase.</div>
        """,
        unsafe_allow_html=True,
    )

with attribution_tab:
    st.subheader("How attribution choice changes budget guidance")
    default_models = ["Last Touch", "Linear", "Markov", "Shapley"]
    selected_models = st.multiselect(
        "Models",
        sorted(data["attribution"]["model"].unique()),
        default=default_models,
    )
    st.plotly_chart(
        attribution_figure(data["attribution"], selected_models),
        width="stretch",
    )

    stage = data["attribution_stage"]
    last_bottom = stage.query(
        "model == 'Last Touch' and funnel_stage == 'Bottom Funnel'"
    )["conversion_credit_share"].iloc[0]
    shapley_bottom = stage.query(
        "model == 'Shapley' and funnel_stage == 'Bottom Funnel'"
    )["conversion_credit_share"].iloc[0]
    shift = last_bottom - shapley_bottom
    st.markdown(
        f"""
        <div class="insight"><b>Core finding:</b> Last Touch assigns
        {last_bottom:.1%} of credit to bottom-funnel placements versus
        {shapley_bottom:.1%} under Shapley—a {shift:.1%} point shift,
        equivalent to ${kpis['spend'] * shift:,.0f} of media-spend share at this scale.
        This is scenario analysis, not causal incrementality.</div>
        """,
        unsafe_allow_html=True,
    )

with campaigns_tab:
    campaigns = data["campaigns"].copy()
    types = st.multiselect(
        "Filter campaign type",
        sorted(campaigns["campaign_type"].unique()),
        default=sorted(campaigns["campaign_type"].unique()),
        key="campaign_types_table",
    )
    filtered = campaigns[campaigns["campaign_type"].isin(types)]
    scatter = px.scatter(
        filtered,
        x="spend",
        y="roas",
        size="revenue",
        color="campaign_type",
        hover_name="campaign_name",
        color_discrete_map=COLORS,
        labels={"spend": "Spend ($)", "roas": "ROAS", "campaign_type": "Type"},
    )
    scatter.add_hline(y=1, line_dash="dash", line_color="#64748B")
    scatter.update_layout(template="plotly_white", height=440)
    st.plotly_chart(scatter, width="stretch")
    display_table = filtered[
        [
            "campaign_name",
            "campaign_type",
            "impressions",
            "clicks",
            "purchases",
            "spend",
            "revenue",
            "ctr",
            "cvr",
            "roas",
            "acos",
        ]
    ].sort_values("roas", ascending=False)
    display_table = display_table.copy()
    display_table[["ctr", "cvr", "acos"]] *= 100
    st.dataframe(
        display_table,
        width="stretch",
        hide_index=True,
        column_config={
            "spend": st.column_config.NumberColumn(format="$%.2f"),
            "revenue": st.column_config.NumberColumn(format="$%.2f"),
            "ctr": st.column_config.NumberColumn(format="%.2f%%"),
            "cvr": st.column_config.NumberColumn(format="%.2f%%"),
            "roas": st.column_config.NumberColumn(format="%.2fx"),
            "acos": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

    budget = data["budget"]
    st.subheader(f"Budget pacing · {budget['campaign_name'].iloc[0]}")
    pacing = go.Figure()
    pacing.add_trace(
        go.Scatter(x=budget["date"], y=budget["spend"], name="Daily Spend")
    )
    pacing.add_trace(
        go.Scatter(
            x=budget["date"],
            y=budget["daily_budget"],
            name="Daily Budget",
            line={"dash": "dash", "color": "#111827"},
        )
    )
    pacing.add_trace(
        go.Scatter(
            x=budget["date"],
            y=budget["rolling_7d"],
            name="7-Day Average",
            line={"color": "#0F766E"},
        )
    )
    anomalies = budget[~budget["severity"].eq("On-Track")]
    pacing.add_trace(
        go.Scatter(
            x=anomalies["date"],
            y=anomalies["spend"],
            name="Anomaly",
            mode="markers",
            marker={"color": "#DC2626", "size": 9, "symbol": "diamond"},
        )
    )
    pacing.update_layout(template="plotly_white", height=400)
    st.plotly_chart(pacing, width="stretch")

with customers_tab:
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("RFM Customer Segments")
        rfm = data["rfm"]
        sample = rfm.sample(min(12_000, len(rfm)), random_state=42)
        rfm_chart = px.scatter(
            sample,
            x="recency_days",
            y="frequency",
            size="monetary",
            color="segment",
            hover_data=["customer_id", "region", "loyalty_tier"],
            size_max=28,
            labels={
                "recency_days": "Recency (days)",
                "frequency": "Purchase Frequency",
            },
        )
        rfm_chart.update_layout(template="plotly_white", height=480)
        st.plotly_chart(rfm_chart, width="stretch")
    with right:
        st.subheader("Segment Mix")
        segment_mix = (
            data["rfm"]["segment"].value_counts().rename_axis("segment").reset_index(
                name="customers"
            )
        )
        mix_chart = px.bar(
            segment_mix,
            x="customers",
            y="segment",
            orientation="h",
            color="segment",
            text_auto=",",
        )
        mix_chart.update_layout(
            template="plotly_white",
            height=480,
            showlegend=False,
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(mix_chart, width="stretch")

    st.subheader("Signup Cohort Retention")
    cohort = data["cohort"].set_index("cohort_month")
    heatmap = go.Figure(
        go.Heatmap(
            z=cohort.values,
            x=[f"Month {i}" for i in range(1, 7)],
            y=cohort.index,
            colorscale="Blues",
            text=np.vectorize(lambda value: f"{value:.1f}%")(cohort.values),
            texttemplate="%{text}",
            colorbar={"title": "Retention"},
        )
    )
    heatmap.update_layout(template="plotly_white", height=430)
    st.plotly_chart(heatmap, width="stretch")

with stack_tab:
    st.subheader("Engineering and analytics stack")
    st.markdown(
        """
        | Capability | Implementation |
        |---|---|
        | Python analytics | pandas, NumPy, Plotly, Streamlit |
        | Data warehouse | PostgreSQL with monthly partitioning |
        | ETL | Validated, idempotent batched `COPY` |
        | Attribution | First/Last Touch, Linear, Time Decay, Markov, Shapley |
        | SQL analytics | Funnel, campaign performance, cohorts, RFM, pacing |
        | Excel | Downloadable executive workbook with native charts |
        | Power BI | Star schema, DAX library, four-page dashboard specification |
        | Quality | pytest unit and PostgreSQL integration tests |
        """
    )
    st.info(
        "Streamlit Cloud uses committed aggregate extracts because a cloud app "
        "cannot reach the developer laptop's local PostgreSQL instance. The full "
        "repository retains the PostgreSQL ETL and SQLAlchemy-connected dashboard layer."
    )
    st.link_button("Open the full source code", GITHUB_URL)
