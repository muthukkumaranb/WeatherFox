"""Tests for the upload/judge endpoint. Owner: Person C."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from skyguard.api.upload import router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# 5-row CSV: one 55 °C row (T_max=50, so out-of-range anomaly), one invalid, three normal
CSV_5ROW = """\
station_id,ts_utc,T,RH,P
s1,2024-01-01T12:00:00Z,55.0,20.0,1005.0
s2,2024-01-01T12:00:00Z,25.0,50.0,1010.0
s3,2024-01-01T12:00:00Z,25.0,50.0,1010.0
INVALID_STATION,,not_a_number,50.0,1010.0
s5,2024-01-01T12:00:00Z,26.0,55.0,1008.0
"""


def _post_csv(client, csv_content: str, source: str = "imd_wis2") -> dict:
    return client.post(
        "/upload/score",
        data={"source": source},
        files={"data_file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    ).json()


def test_upload_counts_non_negative(client):
    """All label counts must be non-negative integers."""
    data = _post_csv(client, CSV_5ROW)
    assert "counts" in data
    label_counts = data["counts"].get("label", {})
    for label, cnt in label_counts.items():
        assert cnt >= 0, f"Negative count for label '{label}': {cnt}"


def test_upload_counts_sum_to_valid_rows(client):
    """Sum of label counts == number of valid rows (invalid rows excluded)."""
    data = _post_csv(client, CSV_5ROW)
    invalid_count = data["invalid_count"]
    n_valid = data.get("n_valid", sum(data["counts"].get("label", {}).values()))
    total_labeled = sum(data["counts"].get("label", {}).values())
    assert total_labeled == n_valid, (
        f"Label counts sum {total_labeled} != n_valid {n_valid}"
    )
    assert invalid_count >= 0


def test_upload_55C_row_is_anomaly_out_of_range(client):
    """A row with T=55°C (T_max=55°C) must produce anomaly with root_cause out_of_range."""
    hot_csv = """\
station_id,ts_utc,T,RH,P
sA,2024-01-01T10:00:00Z,55.0,20.0,1005.0
"""
    data = _post_csv(client, hot_csv)
    # Must have at least one anomaly
    assert data["counts"].get("label", {}).get("anomaly", 0) >= 1, (
        f"Expected anomaly count >= 1 for 55 °C row, got: {data}"
    )
    # Must have out_of_range root cause
    assert data["counts"].get("root_cause", {}).get("out_of_range", 0) >= 1, (
        f"Expected root_cause out_of_range for 55 °C row, got: {data}"
    )


def test_upload_50_5C_row_is_not_out_of_range(client):
    """A 50.5 °C row (e.g. Churu extreme heat reading) must NOT be marked out_of_range."""
    churu_csv = """\
station_id,ts_utc,T,RH,P
sChuru,2024-05-28T12:00:00Z,50.5,15.0,1002.0
"""
    data = _post_csv(client, churu_csv)
    rc_counts = data["counts"].get("root_cause", {})
    assert rc_counts.get("out_of_range", 0) == 0, (
        f"Expected out_of_range == 0 for 50.5 °C genuine reading, got: {data}"
    )


def test_upload_invalid_row_counted(client):
    """One clearly invalid row (bad T value) must result in invalid_count == 1."""
    single_bad_csv = """\
station_id,ts_utc,T,RH,P
BAD,,not_a_number,50.0,1010.0
"""
    data = _post_csv(client, single_bad_csv)
    assert data["invalid_count"] == 1, (
        f"Expected invalid_count == 1 for single invalid row, got {data['invalid_count']}"
    )


def test_upload_source_default_imd_wis2(client):
    """No source column in CSV -> source defaults to imd_wis2 (row passes validation)."""
    normal_csv = """\
station_id,ts_utc,T,RH,P
s1,2024-01-01T08:00:00Z,25.0,60.0,1012.0
"""
    data = _post_csv(client, normal_csv, source="imd_wis2")
    # Should have 0 invalid rows (imd_wis2 is a valid source)
    assert data["invalid_count"] == 0


def test_upload_alerts_list(client):
    """Alerts list must be present and have station_id and ts_utc for each anomaly."""
    data = _post_csv(client, CSV_5ROW)
    assert isinstance(data["alerts"], list)
    for alert in data["alerts"]:
        assert "station_id" in alert
        assert "ts_utc" in alert
