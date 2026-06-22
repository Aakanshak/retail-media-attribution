#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  PYTHON_BIN="python"
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Set valid PostgreSQL credentials, then rerun: bash setup.sh"
  exit 1
fi

"${PYTHON_BIN}" -m venv .venv
if [[ -x ".venv/bin/python" ]]; then
  VENV_PYTHON=".venv/bin/python"
else
  VENV_PYTHON=".venv/Scripts/python.exe"
fi
"${VENV_PYTHON}" -m pip install --upgrade pip
"${VENV_PYTHON}" -m pip install -r requirements.txt
"${VENV_PYTHON}" src/data_generation/generate_data.py --overwrite
"${VENV_PYTHON}" src/etl/load_to_postgres.py --create-schema
"${VENV_PYTHON}" -m src.analysis.run_sql_queries
"${VENV_PYTHON}" -m src.attribution.model_comparison
"${VENV_PYTHON}" -m src.analysis.plotly_dashboard
"${VENV_PYTHON}" -m pytest -q

echo "Pipeline complete: PostgreSQL loaded, SQL outputs generated, attribution modeled, dashboards exported, tests passed."
