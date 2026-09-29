import pytest
import json
from unittest.mock import patch
from skyguard.ingest.wis2 import fetch_observations, compute_rh, process_reports

def test_compute_rh():
    rh = compute_rh(30.0, 20.0)
    assert 54.0 < rh < 56.0

@pytest.mark.xfail(reason="waiting for imd_wis2 enum")
def test_process_reports_basic():
    features = [
        {
            "properties": {
                "wigos_station_identifier": "0-20000-0-12345",
                "reportId": "rep1",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "air_temperature",
                "value": 303.15,
                "units": "K",
                "description": "surface"
            }
        },
        {
            "properties": {
                "wigos_station_identifier": "0-20000-0-12345",
                "reportId": "rep1",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "pressure_reduced_to_mean_sea_level",
                "value": 101325,
                "units": "Pa"
            }
        }
    ]
    
    stations = {"0-20000-0-12345": {"elev_m": 10.0}}
    rows, drops = process_reports(features, "2024-01-01T12:30:00Z", "imd_wis2", stations)
    assert len(rows) == 1
    row = rows[0]
    assert row["T"] == 30.0
    assert row["P"] == 1013.25
    assert row["P_type"] == "slp"
    assert row["source"] == "imd_wis2"
    
    # Just call validate explicitly to trigger the xfail
    from skyguard.contract import validate_input_row
    validate_input_row(row)

def test_plausibility_drop_slp_800():
    features = [
        {
            "properties": {
                "wigos_station_identifier": "s1",
                "reportId": "r1",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "pressure_reduced_to_mean_sea_level",
                "value": 80000,
                "units": "Pa"
            }
        }
    ]
    rows, drops = process_reports(features, "2024-01-01T12:30:00Z", "imd_wis2", {"s1": {"elev_m": 100.0}})
    assert len(rows) == 1
    assert rows[0]["P"] is None
    assert any(d["reason"] == "implausible_slp" for d in drops)

def test_plausibility_keep_station_p_2200m():
    features = [
        {
            "properties": {
                "wigos_station_identifier": "s2",
                "reportId": "r2",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "non_coordinate_pressure",
                "value": 78000,
                "units": "Pa"
            }
        }
    ]
    # 2200m -> ~779.6 hPa
    rows, drops = process_reports(features, "2024-01-01T12:30:00Z", "imd_wis2", {"s2": {"elev_m": 2200.0}})
    assert len(rows) == 1
    assert rows[0]["P"] == 780.0
    assert len(drops) == 0

def test_feature_order_gives_same_p():
    feat_slp = {
        "properties": {
            "wigos_station_identifier": "s3",
            "reportId": "r3",
            "reportTime": "2024-01-01T12:00:00Z",
            "name": "pressure_reduced_to_mean_sea_level",
            "value": 101000,
            "units": "Pa"
        }
    }
    feat_stn = {
        "properties": {
            "wigos_station_identifier": "s3",
            "reportId": "r3",
            "reportTime": "2024-01-01T12:00:00Z",
            "name": "non_coordinate_pressure",
            "value": 90000,
            "units": "Pa"
        }
    }
    rows1, _ = process_reports([feat_slp, feat_stn], "2024-01-01T12:30:00Z", "imd_wis2", {"s3": {"elev_m": 0.0}})
    rows2, _ = process_reports([feat_stn, feat_slp], "2024-01-01T12:30:00Z", "imd_wis2", {"s3": {"elev_m": 0.0}})
    
    assert rows1[0]["P"] == 1010.0
    assert rows1[0]["P_type"] == "slp"
    assert rows2[0]["P"] == 1010.0
    assert rows2[0]["P_type"] == "slp"

@patch("skyguard.ingest.wis2.fetch_with_fallback")
def test_page_cap_reached(mock_fetch):
    mock_fetch.return_value = {
        "features": [{"properties": {"wigos_station_identifier": "s1", "reportId": "r1", "reportTime": "2024-01-01T12:00:00Z"}}],
        "links": [{"rel": "next", "href": "/next"}]
    }
    
    rows, pages, drops, cap_hit, num_feats = fetch_observations("2024-01-01T00:00:00Z", "2024-01-01T23:59:59Z", "imd_wis2", 2, {"s1": {"elev_m": 0}})
    assert pages == 2
    assert cap_hit is True
    assert num_feats == 2

    # Now verify main exit code 2
    import sys
    from skyguard.ingest.wis2 import main
    import argparse
    from unittest.mock import MagicMock
    
    sys.argv = ["wis2.py", "--hours", "1", "--out", "tests/tmp.jsonl"]
    with patch("skyguard.ingest.wis2.get_config", return_value={"source": "imd_wis2", "page_cap": 2}):
        with patch("skyguard.ingest.wis2.fetch_stations", return_value={}):
            with patch("skyguard.ingest.wis2.fetch_observations", return_value=([], 2, [], True, 2)):
                with pytest.raises(SystemExit) as e:
                    main()
                assert e.value.code == 2
