"""Validate generated CSVs and bulk-load them into PostgreSQL.

The loader is intentionally idempotent: one transaction truncates the target
tables and reloads the complete snapshot. If any database operation fails,
PostgreSQL rolls back both the truncate and the partial load.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql


LOGGER = logging.getLogger("retail_media_etl")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TableSpec:
    """CSV-to-table contract and validation behavior."""

    table: str
    filename: str
    columns: tuple[str, ...]
    validator: Callable[[pd.DataFrame], tuple[pd.DataFrame, pd.DataFrame]]
    chunk_size: int | None = None


ID_PATTERNS = {
    "advertiser_id": re.compile(r"^ADV\d{4}$"),
    "product_id": re.compile(r"^PRD\d{6}$"),
    "customer_id": re.compile(r"^CUS\d{7}$"),
    "campaign_id": re.compile(r"^CAM\d{5}$"),
    "event_id": re.compile(r"^EVT\d{10}$"),
    "order_id": re.compile(r"^ORD\d{9}$"),
    "path_id": re.compile(r"^PTH\d{9}$"),
}


def configure_logging(log_file: Path | None) -> None:
    """Configure console logging and an optional persistent log file."""

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def database_connection() -> psycopg.Connection:
    """Create a connection from `.env`/environment credentials."""

    required = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing database environment variables: {', '.join(missing)}")

    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        sslmode=os.getenv("POSTGRES_SSLMODE", "prefer"),
        connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
    )


def mark_invalid(
    reasons: pd.Series,
    mask: pd.Series,
    reason: str,
) -> pd.Series:
    """Attach the first validation failure reason to each invalid row."""

    target = mask.fillna(True) & reasons.eq("")
    reasons.loc[target] = reason
    return reasons


def validate_ids(frame: pd.DataFrame, reasons: pd.Series, columns: list[str]) -> pd.Series:
    """Validate required synthetic key formats."""

    for column in columns:
        valid = frame[column].fillna("").str.fullmatch(ID_PATTERNS[column])
        reasons = mark_invalid(reasons, ~valid, f"invalid {column}")
    return reasons


def parse_datetime(
    frame: pd.DataFrame,
    reasons: pd.Series,
    column: str,
    date_only: bool = False,
) -> pd.Series:
    """Parse a required date/timestamp and normalize its COPY representation."""

    parsed = pd.to_datetime(frame[column], errors="coerce")
    reasons = mark_invalid(reasons, parsed.isna(), f"invalid {column}")
    frame[column] = (
        parsed.dt.strftime("%Y-%m-%d")
        if date_only
        else parsed.dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    return reasons


def parse_numeric(
    frame: pd.DataFrame,
    reasons: pd.Series,
    column: str,
    minimum: float | None = None,
    integer: bool = False,
) -> pd.Series:
    """Parse a numeric field and enforce a lower bound."""

    parsed = pd.to_numeric(frame[column], errors="coerce")
    invalid = parsed.isna()
    if minimum is not None:
        invalid |= parsed < minimum
    if integer:
        invalid |= parsed.notna() & (parsed % 1 != 0)
        frame[column] = parsed.astype("Int64")
    else:
        frame[column] = parsed
    return mark_invalid(reasons, invalid, f"invalid {column}")


def parse_boolean(frame: pd.DataFrame, reasons: pd.Series, column: str) -> pd.Series:
    """Normalize common CSV boolean representations to PostgreSQL literals."""

    normalized = frame[column].fillna("").str.strip().str.lower()
    mapping = {"true": "true", "false": "false", "1": "true", "0": "false"}
    invalid = ~normalized.isin(mapping)
    frame[column] = normalized.map(mapping)
    return mark_invalid(reasons, invalid, f"invalid {column}")


def finish_validation(
    frame: pd.DataFrame, reasons: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split valid rows from rejected rows and retain rejection reasons."""

    rejected = frame.loc[reasons.ne("")].copy()
    rejected.insert(0, "rejection_reason", reasons.loc[reasons.ne("")])
    valid = frame.loc[reasons.eq("")].copy()
    return valid, rejected


def validate_advertisers(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["advertiser_id"])
    reasons = parse_datetime(frame, reasons, "join_date", date_only=True)
    reasons = mark_invalid(
        reasons,
        ~frame["tier"].isin(["Enterprise", "Mid-Market", "SMB"]),
        "invalid tier",
    )
    reasons = mark_invalid(
        reasons,
        frame[["brand_name", "category"]].isna().any(axis=1),
        "missing required text",
    )
    return finish_validation(frame, reasons)


def validate_products(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["product_id", "advertiser_id"])
    reasons = parse_numeric(frame, reasons, "base_price", minimum=0.01)
    reasons = parse_numeric(frame, reasons, "cost_per_unit", minimum=0)
    reasons = mark_invalid(
        reasons,
        frame["cost_per_unit"] > frame["base_price"],
        "cost_per_unit exceeds base_price",
    )
    reasons = mark_invalid(
        reasons,
        frame[["product_name", "category", "subcategory"]].isna().any(axis=1),
        "missing required text",
    )
    return finish_validation(frame, reasons)


def validate_customers(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["customer_id"])
    reasons = parse_datetime(frame, reasons, "signup_date", date_only=True)
    reasons = mark_invalid(
        reasons,
        ~frame["loyalty_tier"].isin(["Bronze", "Silver", "Gold", "Platinum"]),
        "invalid loyalty_tier",
    )
    reasons = mark_invalid(
        reasons,
        ~frame["region"].isin(["Northeast", "Midwest", "South", "West"]),
        "invalid region",
    )
    reasons = mark_invalid(
        reasons,
        ~frame["device_preference"].isin(["mobile", "desktop", "tablet"]),
        "invalid device_preference",
    )
    return finish_validation(frame, reasons)


def validate_campaigns(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["campaign_id", "advertiser_id"])
    reasons = parse_datetime(frame, reasons, "start_date", date_only=True)
    reasons = parse_datetime(frame, reasons, "end_date", date_only=True)
    reasons = parse_numeric(frame, reasons, "daily_budget", minimum=0.01)
    reasons = parse_numeric(frame, reasons, "target_acos", minimum=0.0001)
    reasons = mark_invalid(
        reasons,
        ~frame["campaign_type"].isin(
            ["Sponsored Product", "Sponsored Brand", "Display", "Video"]
        ),
        "invalid campaign_type",
    )
    reasons = mark_invalid(
        reasons,
        pd.to_datetime(frame["end_date"], errors="coerce")
        < pd.to_datetime(frame["start_date"], errors="coerce"),
        "end_date before start_date",
    )
    return finish_validation(frame, reasons)


def validate_ad_events(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(
        frame,
        reasons,
        ["event_id", "campaign_id", "customer_id", "product_id"],
    )
    reasons = parse_datetime(frame, reasons, "event_timestamp")
    reasons = parse_numeric(frame, reasons, "cost", minimum=0)
    reasons = mark_invalid(
        reasons,
        ~frame["event_type"].isin(["impression", "click", "add_to_cart", "purchase"]),
        "invalid event_type",
    )
    reasons = mark_invalid(
        reasons,
        ~frame["placement"].isin(
            [
                "search_top",
                "search_carousel",
                "product_page",
                "category_page",
                "offsite_display",
            ]
        ),
        "invalid placement",
    )
    reasons = mark_invalid(
        reasons,
        ~frame["device_type"].isin(["mobile", "desktop", "tablet"]),
        "invalid device_type",
    )
    return finish_validation(frame, reasons)


def validate_orders(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["order_id", "customer_id", "product_id"])
    reasons = parse_datetime(frame, reasons, "order_timestamp")
    reasons = parse_numeric(frame, reasons, "quantity", minimum=1, integer=True)
    reasons = parse_numeric(frame, reasons, "unit_price", minimum=0.01)
    reasons = parse_numeric(frame, reasons, "order_total", minimum=0.01)
    reasons = parse_boolean(frame, reasons, "is_organic")

    purchase_id = frame["purchase_event_id"].fillna("")
    populated = purchase_id.ne("")
    valid_purchase_id = purchase_id.str.fullmatch(ID_PATTERNS["event_id"])
    reasons = mark_invalid(
        reasons,
        populated & ~valid_purchase_id,
        "invalid purchase_event_id",
    )
    organic = frame["is_organic"].eq("true")
    reasons = mark_invalid(
        reasons,
        organic & populated,
        "organic order has purchase_event_id",
    )
    reasons = mark_invalid(
        reasons,
        ~organic & ~populated,
        "paid order missing purchase_event_id",
    )
    frame.loc[~populated, "purchase_event_id"] = pd.NA
    return finish_validation(frame, reasons)


def validate_journeys(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = pd.Series("", index=frame.index, dtype="string")
    reasons = validate_ids(frame, reasons, ["path_id", "customer_id", "product_id"])
    reasons = parse_datetime(frame, reasons, "path_start_timestamp")
    reasons = parse_datetime(frame, reasons, "path_end_timestamp")
    reasons = parse_numeric(frame, reasons, "touchpoint_count", minimum=1, integer=True)
    reasons = parse_numeric(frame, reasons, "lookback_days", minimum=1, integer=True)
    reasons = parse_boolean(frame, reasons, "conversion_flag")
    reasons = mark_invalid(
        reasons,
        pd.to_datetime(frame["path_end_timestamp"], errors="coerce")
        < pd.to_datetime(frame["path_start_timestamp"], errors="coerce"),
        "path_end_timestamp before path_start_timestamp",
    )

    json_valid = pd.Series(True, index=frame.index)
    json_lengths = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    for index, value in frame["ordered_touchpoints"].items():
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("touchpoints must be a JSON array")
            json_lengths.at[index] = len(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            json_valid.at[index] = False
    reasons = mark_invalid(reasons, ~json_valid, "invalid ordered_touchpoints JSON")
    reasons = mark_invalid(
        reasons,
        json_valid & json_lengths.ne(frame["touchpoint_count"]),
        "touchpoint_count does not match JSON length",
    )

    order_id = frame["order_id"].fillna("")
    populated = order_id.ne("")
    valid_order_id = order_id.str.fullmatch(ID_PATTERNS["order_id"])
    reasons = mark_invalid(reasons, populated & ~valid_order_id, "invalid order_id")
    converted = frame["conversion_flag"].eq("true")
    reasons = mark_invalid(reasons, converted & ~populated, "converted path missing order_id")
    reasons = mark_invalid(reasons, ~converted & populated, "non-converting path has order_id")
    frame.loc[~populated, "order_id"] = pd.NA
    return finish_validation(frame, reasons)


TABLE_SPECS = (
    TableSpec(
        "dim_advertisers",
        "dim_advertisers.csv",
        ("advertiser_id", "brand_name", "category", "tier", "join_date"),
        validate_advertisers,
    ),
    TableSpec(
        "dim_products",
        "dim_products.csv",
        (
            "product_id", "advertiser_id", "product_name", "category",
            "subcategory", "base_price", "cost_per_unit",
        ),
        validate_products,
    ),
    TableSpec(
        "dim_customers",
        "dim_customers.csv",
        ("customer_id", "signup_date", "loyalty_tier", "region", "device_preference"),
        validate_customers,
    ),
    TableSpec(
        "dim_campaigns",
        "dim_campaigns.csv",
        (
            "campaign_id", "advertiser_id", "campaign_name", "campaign_type",
            "start_date", "end_date", "daily_budget", "target_acos",
        ),
        validate_campaigns,
    ),
    TableSpec(
        "fact_ad_events",
        "fact_ad_events.csv",
        (
            "event_id", "campaign_id", "customer_id", "product_id",
            "event_timestamp", "event_type", "placement", "device_type", "cost",
        ),
        validate_ad_events,
        chunk_size=250_000,
    ),
    TableSpec(
        "fact_orders",
        "fact_orders.csv",
        (
            "order_id", "customer_id", "order_timestamp", "product_id",
            "quantity", "unit_price", "order_total", "is_organic",
            "purchase_event_id",
        ),
        validate_orders,
    ),
    TableSpec(
        "fact_customer_journey",
        "fact_customer_journey.csv",
        (
            "path_id", "customer_id", "product_id", "path_start_timestamp",
            "path_end_timestamp", "ordered_touchpoints", "touchpoint_count",
            "conversion_flag", "order_id", "lookback_days",
        ),
        validate_journeys,
        chunk_size=25_000,
    ),
)


def apply_schema(connection: psycopg.Connection, schema_dir: Path) -> None:
    """Execute table DDL files in lexical dependency order."""

    ddl_files = sorted(schema_dir.glob("[0-9][0-9]_*.sql"))
    if not ddl_files:
        raise FileNotFoundError(f"No numbered DDL files found in {schema_dir}")
    for ddl_file in ddl_files:
        LOGGER.info("Applying schema file %s", ddl_file.name)
        connection.execute(ddl_file.read_text(encoding="utf-8"))


def read_csv_chunks(path: Path, spec: TableSpec) -> Iterator[pd.DataFrame]:
    """Read all columns as strings so validation controls type coercion."""

    reader = pd.read_csv(
        path,
        dtype="string",
        chunksize=spec.chunk_size,
        keep_default_na=True,
    )
    if spec.chunk_size:
        yield from reader
    else:
        yield reader


def assert_columns(frame: pd.DataFrame, spec: TableSpec) -> None:
    """Fail fast when a source file does not match its declared contract."""

    actual = tuple(frame.columns)
    if actual != spec.columns:
        raise ValueError(
            f"{spec.filename} schema mismatch. Expected {spec.columns}; got {actual}"
        )


def write_rejections(rejected: pd.DataFrame, path: Path, first_write: bool) -> None:
    """Persist rejected rows with their first validation failure reason."""

    if rejected.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(
        path,
        mode="w" if first_write else "a",
        header=first_write,
        index=False,
    )


def copy_frame(
    connection: psycopg.Connection,
    table: str,
    columns: tuple[str, ...],
    frame: pd.DataFrame,
) -> None:
    """Bulk-copy a validated DataFrame into PostgreSQL.

    COPY sends a batch through PostgreSQL's optimized bulk-ingestion path. It
    avoids one SQL parse, network round trip, and transaction bookkeeping cycle
    per row, making it dramatically faster than row-by-row INSERTs for 9M rows.
    """

    if frame.empty:
        return
    buffer = io.StringIO()
    frame.loc[:, columns].to_csv(
        buffer,
        index=False,
        header=False,
        na_rep="\\N",
        lineterminator="\n",
    )
    buffer.seek(0)
    copy_statement = sql.SQL(
        "COPY {} ({}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
    ).format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    with connection.cursor() as cursor:
        with cursor.copy(copy_statement) as copy:
            copy.write(buffer.getvalue())


def truncate_targets(connection: psycopg.Connection) -> None:
    """Clear the snapshot atomically in reverse dependency order."""

    connection.execute(
        """
        TRUNCATE TABLE
            fact_customer_journey,
            fact_orders,
            fact_ad_events,
            dim_campaigns,
            dim_products,
            dim_customers,
            dim_advertisers;
        """
    )


def load_table(
    connection: psycopg.Connection,
    data_dir: Path,
    reject_dir: Path,
    spec: TableSpec,
) -> tuple[int, int, int]:
    """Validate and COPY one source file, returning read/loaded/rejected counts."""

    source = data_dir / spec.filename
    if not source.exists():
        raise FileNotFoundError(source)

    rows_read = 0
    rows_loaded = 0
    rows_rejected = 0
    rejection_path = reject_dir / f"{spec.table}_rejected.csv"
    if rejection_path.exists():
        rejection_path.unlink()
    first_rejection_write = True

    LOGGER.info("Starting %s from %s", spec.table, source)
    for chunk_number, chunk in enumerate(read_csv_chunks(source, spec), start=1):
        assert_columns(chunk, spec)
        rows_read += len(chunk)
        valid, rejected = spec.validator(chunk)
        copy_frame(connection, spec.table, spec.columns, valid)
        write_rejections(rejected, rejection_path, first_rejection_write)
        if not rejected.empty:
            first_rejection_write = False
        rows_loaded += len(valid)
        rows_rejected += len(rejected)
        LOGGER.info(
            "%s chunk %s: read=%s loaded=%s rejected=%s",
            spec.table,
            chunk_number,
            f"{len(chunk):,}",
            f"{len(valid):,}",
            f"{len(rejected):,}",
        )

    LOGGER.info(
        "Completed %s: read=%s loaded=%s rejected=%s",
        spec.table,
        f"{rows_read:,}",
        f"{rows_loaded:,}",
        f"{rows_rejected:,}",
    )
    return rows_read, rows_loaded, rows_rejected


def verify_database_integrity(connection: psycopg.Connection) -> None:
    """Check lineage constraints that cannot be declared as partitioned FKs."""

    missing_purchase_events = connection.execute(
        """
        SELECT count(*)
        FROM fact_orders AS o
        LEFT JOIN fact_ad_events AS e
          ON e.event_id = o.purchase_event_id
         AND e.event_timestamp = o.order_timestamp
         AND e.event_type = 'purchase'
        WHERE NOT o.is_organic
          AND e.event_id IS NULL;
        """
    ).fetchone()[0]
    if missing_purchase_events:
        raise ValueError(
            f"{missing_purchase_events:,} paid orders lack a matching purchase event"
        )

    default_partition_rows = connection.execute(
        "SELECT count(*) FROM fact_ad_events_default"
    ).fetchone()[0]
    if default_partition_rows:
        LOGGER.warning(
            "%s event rows landed in the default partition; inspect date coverage",
            f"{default_partition_rows:,}",
        )


def load_snapshot(
    connection: psycopg.Connection,
    data_dir: Path,
    reject_dir: Path,
    create_schema: bool,
) -> None:
    """Load all tables in dependency order as one atomic snapshot."""

    totals = {"read": 0, "loaded": 0, "rejected": 0}
    with connection.transaction():
        if create_schema:
            apply_schema(connection, PROJECT_ROOT / "sql" / "schema")
        truncate_targets(connection)
        for spec in TABLE_SPECS:
            read, loaded, rejected = load_table(
                connection, data_dir, reject_dir, spec
            )
            totals["read"] += read
            totals["loaded"] += loaded
            totals["rejected"] += rejected
        verify_database_integrity(connection)
        connection.execute("ANALYZE")

    LOGGER.info(
        "ETL committed successfully: read=%s loaded=%s rejected=%s",
        f"{totals['read']:,}",
        f"{totals['loaded']:,}",
        f"{totals['rejected']:,}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
        help="Directory containing generated CSV files.",
    )
    parser.add_argument(
        "--reject-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "rejected",
        help="Destination for rejected rows and reasons.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="dotenv file containing PostgreSQL credentials.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Apply numbered DDL files before truncating and loading.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "etl.log",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_file)
    load_dotenv(args.env_file)
    LOGGER.info("Connecting to PostgreSQL database %s", os.getenv("POSTGRES_DB"))
    with database_connection() as connection:
        load_snapshot(
            connection,
            args.data_dir.resolve(),
            args.reject_dir.resolve(),
            args.create_schema,
        )


if __name__ == "__main__":
    main()
