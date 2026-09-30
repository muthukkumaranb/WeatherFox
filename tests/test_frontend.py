"""The WeatherFox dashboard: served routes, offline assets, and the API fields it depends on."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skyguard.api.main import create_app, state

DASH = Path(__file__).resolve().parent.parent / "dashboard"


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_dashboard_and_assets_are_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "WeatherFox" in r.text
    for path in ("/app/core.js", "/app/app.css", "/vendor/tailwind.css", "/vendor/fonts.css",
                 "/vendor/fonts/material-symbols-outlined.woff2", "/vendor/chart.js",
                 "/vendor/india_states.geojson", "/logo.png", "/classic"):
        assert client.get(path).status_code == 200, path


def test_dashboard_loads_nothing_from_the_internet():
    """Everything must be local so the demo works with no network."""
    files = [DASH / "index.html", DASH / "vendor" / "fonts.css", *sorted((DASH / "app").glob("*"))]
    pattern = re.compile(r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|fetch\(\s*["']https?://""")
    offenders = [str(f.name) for f in files if pattern.search(f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_no_mock_claims_in_dashboard():
    """Numbers and claims from the mock design that were never measured must not come back."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in [DASH / "index.html", *(DASH / "app").glob("*.js")])
    for claim in ("98.4", "99.1%", "0.984", "INSAT", "Mungeshpur", "Priya", "335", "8.5x", "LSTM", "Kriging"):
        assert claim not in text, claim


def test_config_endpoint(client):
    cfg = client.get("/config").json()
    assert {"rule_gate", "conformal", "replay", "scorer"} <= set(cfg)
    assert cfg["conformal"]["alpha_anomaly"] < cfg["conformal"]["alpha_uncertain"]


def test_stations_carry_latest_values(client):
    stations = client.get("/stations").json()
    assert stations
    for s in stations:
        assert set(s["latest"]) == {"T", "RH", "P"}
        assert isinstance(s["flagged_vars"], list)


def test_health_reports_no_data_instead_of_a_made_up_score(client):
    state.verdicts_by_station.clear()
    state.add_verdict({"station_id": "X1", "ts_utc": "2024-05-24T00:00:00Z", "label": "normal", "vars": {}})
    rows = [h for h in client.get("/health/sensors").json() if h["station_id"] == "X1"]
    assert rows and all(h["score"] is None and h["trend"] == "no_data" and h["ttm_days"] is None for h in rows)


def test_health_tracker_never_invents_time_to_maintenance():
    from skyguard.verdict.health import HealthTracker
    t = HealthTracker()
    for _ in range(30):
        score, trend, ttm = t.update_health("S", "T", "anomaly", 5.0)
    assert trend == "declining" and ttm is None
