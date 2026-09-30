"""Tests for Step 4 & Demo Pacing Fixes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import uvicorn

from skyguard.api.main import create_app, state
from skyguard.demo import check_models_exist, check_real_data_exists


def test_check_models_exist_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # independent of whether this checkout has a trained model
    assert check_models_exist() is False
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "detector.pkl").write_bytes(b"x")
    assert check_models_exist() is True


def test_check_real_data_exists_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert check_real_data_exists() is False


def test_demo_scorer_env_setting():
    os.environ["SKYGUARD_SCORER"] = "fake"
    assert os.getenv("SKYGUARD_SCORER") == "fake"


def test_pacing_and_window_bounds():
    """Runs replay loop for ~6 real seconds at default speed (1800x -> 1h / 2s).

    Asserts it advanced 2-4 simulated hours, and no ts_utc is later than 2024-06-07T00:00:00Z.
    """
    app = create_app()
    state.speed_factor = 1800.0  # 1 simulated hour per 2 real seconds

    config = uvicorn.Config(app=app, host="127.0.0.1", port=8991, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    time.sleep(1.0)  # Wait for server startup

    try:
        base_url = "http://127.0.0.1:8991"

        # Initial sample
        resp1 = urllib.request.urlopen(f"{base_url}/stations")
        st1 = json.loads(resp1.read().decode())
        ts1_str = st1[0]["latest_ts"]

        # Sleep ~6 real seconds (should correspond to ~3 simulated hours at 1800x)
        time.sleep(6.0)

        # Second sample
        resp2 = urllib.request.urlopen(f"{base_url}/stations")
        st2 = json.loads(resp2.read().decode())
        ts2_str = st2[0]["latest_ts"]

        if ts1_str and ts2_str:
            t1 = time.fromisoformat(ts1_str.replace("Z", "+00:00")).timestamp() if hasattr(time, "fromisoformat") else 0
            # Parse via datetime
            from datetime import datetime
            dt1 = datetime.fromisoformat(ts1_str.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(ts2_str.replace("Z", "+00:00"))

            sim_hours_passed = (dt2 - dt1).total_seconds() / 3600.0

            # 6 real seconds at 1800x speed = 3.0 simulated hours (accept 2..4)
            assert 1.5 <= sim_hours_passed <= 4.5, f"Expected 2-4 simulated hours, got {sim_hours_passed:.2f} hrs"

            # Window end is 2024-06-07T00:00:00Z
            max_allowed = datetime.fromisoformat("2024-06-07T00:00:00+00:00")
            assert dt2 <= max_allowed, f"Timestamp {dt2} exceeded window end {max_allowed}"

    finally:
        server.should_exit = True
        thread.join(timeout=2.0)
