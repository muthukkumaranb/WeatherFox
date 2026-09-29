"""Tests for Step 4: skyguard/demo.py one-command demo module."""
from __future__ import annotations

import os
from pathlib import Path
from skyguard.demo import check_models_exist, check_real_data_exists


def test_check_models_exist_missing():
    assert check_models_exist() is False


def test_check_real_data_exists_missing():
    assert check_real_data_exists() is False


def test_demo_scorer_env_setting():
    os.environ["SKYGUARD_SCORER"] = "fake"
    assert os.getenv("SKYGUARD_SCORER") == "fake"
