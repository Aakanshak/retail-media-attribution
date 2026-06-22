"""Smoke test the deployed Streamlit application."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_renders_without_exceptions():
    app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)

    assert not app.exception
    assert len(app.tabs) == 5
    assert app.tabs[0].label == "Executive Overview"
    assert app.tabs[1].label == "Attribution"

