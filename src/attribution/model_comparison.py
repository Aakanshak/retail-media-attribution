"""Run rule-based, Markov, and Shapley attribution on the same journeys."""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
import plotly.express as px

from src.attribution.common import Journey, channel_name, load_journeys
from src.attribution.markov_chain_attribution import fit_markov_attribution
from src.attribution.rule_based_models import (
    first_touch,
    last_touch,
    linear,
    time_decay,
)
from src.attribution.shapley_attribution import fit_shapley_attribution


LOGGER = logging.getLogger("attribution_comparison")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def channel_stage(channel: str) -> str:
    """Classify channels for interview-friendly funnel interpretation."""

    if channel.startswith(("Display", "Video")) or "offsite_display" in channel:
        return "Upper Funnel"
    if channel.startswith("Sponsored Brand") or "category_page" in channel:
        return "Mid Funnel"
    return "Bottom Funnel"


def aggregate_rule_based_model(
    journeys: Sequence[Journey],
    model: Callable[[Sequence[dict[str, str]]], list[float]],
    granularity: str,
) -> dict[str, dict[str, float]]:
    """Aggregate touchpoint-level credits into channel conversions and revenue."""

    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"attributed_conversions": 0.0, "attributed_revenue": 0.0}
    )
    for journey in journeys:
        if not journey.converted:
            continue
        credits = model(journey.touchpoints)
        for touchpoint, credit in zip(journey.touchpoints, credits):
            if credit <= 0:
                continue
            channel = channel_name(touchpoint, granularity)
            totals[channel]["attributed_conversions"] += credit
            totals[channel]["attributed_revenue"] += credit * journey.revenue
    return dict(totals)


def aggregate_global_weights(
    weights: dict[str, float],
    total_conversions: int,
    total_revenue: float,
) -> dict[str, dict[str, float]]:
    """Convert model-level channel shares into attributed business outcomes."""

    return {
        channel: {
            "attributed_conversions": weight * total_conversions,
            "attributed_revenue": weight * total_revenue,
        }
        for channel, weight in weights.items()
    }


def load_channel_spend(
    events_path: Path,
    campaigns_path: Path,
    granularity: str,
    chunk_size: int = 500_000,
) -> pd.DataFrame:
    """Aggregate event cost without loading the 9M-row fact into memory."""

    campaigns = pd.read_csv(
        campaigns_path,
        usecols=["campaign_id", "campaign_type"],
        dtype="string",
    )
    campaign_type_by_id = campaigns.set_index("campaign_id")["campaign_type"]
    totals: dict[str, float] = defaultdict(float)
    for chunk_number, chunk in enumerate(
        pd.read_csv(
            events_path,
            usecols=["campaign_id", "placement", "cost"],
            dtype={"campaign_id": "string", "placement": "string"},
            chunksize=chunk_size,
        ),
        start=1,
    ):
        chunk["campaign_type"] = chunk["campaign_id"].map(campaign_type_by_id)
        if chunk["campaign_type"].isna().any():
            raise ValueError("event file contains campaign IDs absent from dim_campaigns")
        if granularity == "campaign_type":
            chunk["channel"] = chunk["campaign_type"]
        elif granularity == "placement":
            chunk["channel"] = chunk["placement"]
        else:
            chunk["channel"] = (
                chunk["campaign_type"] + " | " + chunk["placement"]
            )
        spend = chunk.groupby("channel", observed=True)["cost"].sum()
        for channel, value in spend.items():
            totals[str(channel)] += float(value)
        LOGGER.info("Aggregated spend chunk %s", chunk_number)
    return pd.DataFrame(
        {"channel": list(totals), "spend": list(totals.values())}
    )


def comparison_table(
    journeys: Sequence[Journey],
    spend: pd.DataFrame,
    granularity: str = "campaign_type_placement",
    shapley_max_channels: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every model and return long and interview-friendly wide tables."""

    total_conversions = sum(journey.converted for journey in journeys)
    total_revenue = sum(journey.revenue for journey in journeys if journey.converted)
    rule_models = {
        "First Touch": first_touch,
        "Last Touch": last_touch,
        "Linear": linear,
        "Time Decay": time_decay,
    }
    model_results = {
        model_name: aggregate_rule_based_model(journeys, model, granularity)
        for model_name, model in rule_models.items()
    }

    LOGGER.info("Fitting Markov removal-effect model")
    markov = fit_markov_attribution(journeys, granularity)
    model_results["Markov"] = aggregate_global_weights(
        markov.normalized_credit, total_conversions, total_revenue
    )

    LOGGER.info("Fitting exact Shapley model with at most %s players", shapley_max_channels)
    shapley = fit_shapley_attribution(
        journeys,
        granularity=granularity,
        max_channels=shapley_max_channels,
    )
    model_results["Shapley"] = aggregate_global_weights(
        shapley.normalized_credit, total_conversions, total_revenue
    )

    all_channels = sorted(
        set(spend["channel"])
        | {
            channel
            for result in model_results.values()
            for channel in result
        }
    )
    spend_by_channel = spend.set_index("channel")["spend"].to_dict()
    rows: list[dict[str, object]] = []
    for model_name, result in model_results.items():
        for channel in all_channels:
            outcomes = result.get(
                channel,
                {"attributed_conversions": 0.0, "attributed_revenue": 0.0},
            )
            channel_spend = float(spend_by_channel.get(channel, 0.0))
            revenue = float(outcomes["attributed_revenue"])
            rows.append(
                {
                    "model": model_name,
                    "channel": channel,
                    "funnel_stage": channel_stage(channel),
                    "attributed_conversions": float(
                        outcomes["attributed_conversions"]
                    ),
                    "conversion_credit_share": (
                        float(outcomes["attributed_conversions"])
                        / total_conversions
                        if total_conversions
                        else 0.0
                    ),
                    "attributed_revenue": revenue,
                    "spend": channel_spend,
                    "attributed_roas": (
                        revenue / channel_spend if channel_spend else float("nan")
                    ),
                }
            )

    long_table = pd.DataFrame(rows)
    metric_columns = [
        "attributed_conversions",
        "conversion_credit_share",
        "attributed_revenue",
        "attributed_roas",
    ]
    wide = long_table.pivot(
        index=["channel", "funnel_stage", "spend"],
        columns="model",
        values=metric_columns,
    )
    wide.columns = [
        f"{model.lower().replace(' ', '_')}_{metric}"
        for metric, model in wide.columns
    ]
    wide = wide.reset_index()
    if {
        "last_touch_conversion_credit_share",
        "markov_conversion_credit_share",
    }.issubset(wide.columns):
        wide["markov_minus_last_touch_credit_pp"] = 100 * (
            wide["markov_conversion_credit_share"]
            - wide["last_touch_conversion_credit_share"]
        )
    if {
        "last_touch_conversion_credit_share",
        "shapley_conversion_credit_share",
    }.issubset(wide.columns):
        wide["shapley_minus_last_touch_credit_pp"] = 100 * (
            wide["shapley_conversion_credit_share"]
            - wide["last_touch_conversion_credit_share"]
        )
    wide = wide.sort_values(
        ["funnel_stage", "channel"],
        kind="stable",
    )
    return long_table, wide


def write_money_chart(stage_summary: pd.DataFrame, output_path: Path) -> None:
    """Write an interactive comparison of conversion-credit allocation."""

    chart_data = stage_summary.copy()
    chart_data["credit_share_pct"] = 100 * chart_data["conversion_credit_share"]
    model_order = [
        "First Touch",
        "Last Touch",
        "Linear",
        "Time Decay",
        "Markov",
        "Shapley",
    ]
    stage_order = ["Upper Funnel", "Mid Funnel", "Bottom Funnel"]
    figure = px.bar(
        chart_data,
        x="model",
        y="credit_share_pct",
        color="funnel_stage",
        category_orders={
            "model": model_order,
            "funnel_stage": stage_order,
        },
        color_discrete_map={
            "Upper Funnel": "#4C78A8",
            "Mid Funnel": "#F2CF5B",
            "Bottom Funnel": "#E45756",
        },
        labels={
            "model": "Attribution model",
            "credit_share_pct": "Attributed conversion credit (%)",
            "funnel_stage": "Funnel stage",
        },
        title="How Attribution Choice Changes Channel Credit",
        hover_data={
            "attributed_conversions": ":,.1f",
            "attributed_roas": ":.2f",
            "credit_share_pct": ":.1f",
        },
    )
    figure.update_layout(
        barmode="stack",
        yaxis_range=[0, 100],
        legend_title_text="Funnel stage",
        template="plotly_white",
    )
    figure.write_html(output_path, include_plotlyjs="cdn")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed",
    )
    parser.add_argument(
        "--granularity",
        choices=["campaign_type", "placement", "campaign_type_placement"],
        default="campaign_type_placement",
    )
    parser.add_argument("--shapley-max-channels", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = parse_args()
    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Loading customer journeys and order revenue")
    journeys = load_journeys(
        data_dir / "fact_customer_journey.csv",
        data_dir / "fact_orders.csv",
    )
    LOGGER.info(
        "Loaded %s paths with %s conversions",
        f"{len(journeys):,}",
        f"{sum(journey.converted for journey in journeys):,}",
    )
    spend = load_channel_spend(
        data_dir / "fact_ad_events.csv",
        data_dir / "dim_campaigns.csv",
        args.granularity,
    )
    long_table, wide_table = comparison_table(
        journeys,
        spend,
        granularity=args.granularity,
        shapley_max_channels=args.shapley_max_channels,
    )
    long_path = output_dir / "attribution_model_comparison_long.csv"
    wide_path = output_dir / "attribution_model_comparison.csv"
    long_table.to_csv(long_path, index=False)
    wide_table.to_csv(wide_path, index=False)

    stage_summary = (
        long_table.groupby(["model", "funnel_stage"], as_index=False)
        .agg(
            attributed_conversions=("attributed_conversions", "sum"),
            conversion_credit_share=("conversion_credit_share", "sum"),
            attributed_revenue=("attributed_revenue", "sum"),
            spend=("spend", "sum"),
        )
    )
    stage_summary["attributed_roas"] = (
        stage_summary["attributed_revenue"] / stage_summary["spend"]
    )
    last_touch_share = (
        stage_summary[stage_summary["model"].eq("Last Touch")]
        .set_index("funnel_stage")["conversion_credit_share"]
        .to_dict()
    )
    stage_summary["credit_change_vs_last_touch_pp"] = stage_summary.apply(
        lambda row: 100
        * (
            row["conversion_credit_share"]
            - last_touch_share.get(row["funnel_stage"], 0.0)
        ),
        axis=1,
    )
    stage_path = output_dir / "attribution_model_comparison_by_stage.csv"
    stage_summary.to_csv(stage_path, index=False)
    chart_path = PROJECT_ROOT / "dashboards" / "plotly" / "attribution_money_chart.html"
    write_money_chart(stage_summary, chart_path)

    LOGGER.info("Wrote %s", long_path)
    LOGGER.info("Wrote %s", wide_path)
    LOGGER.info("Wrote %s", stage_path)
    LOGGER.info("Wrote %s", chart_path)


if __name__ == "__main__":
    main()
