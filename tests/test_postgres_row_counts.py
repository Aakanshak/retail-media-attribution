"""Post-load row-count integrity tests for a configured PostgreSQL instance."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv
from psycopg import sql

from src.etl.load_to_postgres import PROJECT_ROOT, TABLE_SPECS, database_connection


pytestmark = pytest.mark.integration


def csv_row_count(path: Path, chunk_size: int = 500_000) -> int:
    """Count source rows without loading a large CSV into memory."""

    return sum(
        len(chunk)
        for chunk in pd.read_csv(path, usecols=[0], chunksize=chunk_size)
    )


def postgres_is_configured() -> bool:
    """Require explicit opt-in so normal unit tests never depend on local state."""

    return os.getenv("RUN_POSTGRES_INTEGRATION") == "1"


@pytest.mark.skipif(
    not postgres_is_configured(),
    reason="Set RUN_POSTGRES_INTEGRATION=1 to verify a loaded PostgreSQL database.",
)
def test_loaded_postgres_row_counts_match_source_csvs():
    load_dotenv(PROJECT_ROOT / ".env")
    data_dir = PROJECT_ROOT / "data" / "raw"

    with database_connection() as connection:
        for spec in TABLE_SPECS:
            expected = csv_row_count(data_dir / spec.filename)
            statement = sql.SQL("SELECT count(*) FROM {}").format(
                sql.Identifier(spec.table)
            )
            actual = connection.execute(statement).fetchone()[0]
            assert actual == expected, (
                f"{spec.table}: PostgreSQL has {actual:,} rows, "
                f"but {spec.filename} has {expected:,}"
            )

