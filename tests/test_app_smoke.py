from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "outputs" / "i-married-a-broken-soldier" / "promos.json"


def test_app_loads_without_errors():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Hookline"
    assert len(at.tabs) == 4


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample run not generated yet")
def test_app_shows_ranked_sample_promos():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert any("#1 ·" in m.value for m in at.markdown)
