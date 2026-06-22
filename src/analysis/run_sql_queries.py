"""Execute documented analytical SQL files and export their result sets."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from src.analysis.plotly_dashboard import PROJECT_ROOT, create_postgres_engine


LOGGER = logging.getLogger("sql_query_runner")


def execute_query(engine: Engine, query_path: Path) -> pd.DataFrame:
    """Execute one read-only analytical query through SQLAlchemy."""

    statement = query_path.read_text(encoding="utf-8")
    with engine.connect() as connection:
        return pd.read_sql_query(text(statement), connection)


def run_all_queries(
    engine: Engine,
    query_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """Execute every named analytical query and save reproducible CSV outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for query_path in sorted(query_dir.glob("*.sql")):
        if query_path.name.startswith("."):
            continue
        LOGGER.info("Executing %s", query_path.name)
        result = execute_query(engine, query_path)
        output_path = output_dir / f"{query_path.stem}.csv"
        result.to_csv(output_path, index=False)
        outputs.append(output_path)
        LOGGER.info("Wrote %s rows to %s", f"{len(result):,}", output_path)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
    )
    parser.add_argument(
        "--query-dir",
        type=Path,
        default=PROJECT_ROOT / "sql" / "queries",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "sql_results",
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
        run_all_queries(
            engine,
            args.query_dir.resolve(),
            args.output_dir.resolve(),
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

