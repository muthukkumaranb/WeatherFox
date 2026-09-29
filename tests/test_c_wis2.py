import pytest
import json
from unittest.mock import patch
from skyguard.ingest.wis2 import fetch_observations, compute_rh, process_reports

def test_compute_rh():
    # T=30, Td=20 -> approx RH 55-56%
    rh = compute_rh(30.0, 20.0)
    assert 54.0 < rh < 56.0

def test_process_reports():
    features = [
        {
            "properties": {
                "wigos_station_identifier": "0-20000-0-12345",
                "reportId": "rep1",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "air_temperature",
                "value": 303.15, # 30 C
                "units": "K"
            }
        },
        {
            "properties": {
                "wigos_station_identifier": "0-20000-0-12345",
                "reportId": "rep1",
                "reportTime": "2024-01-01T12:00:00Z",
                "name": "pressure_reduced_to_mean_sea_level",
                "value": 101325, # 1013.25 hPa
                "units": "Pa"
            }
        }
    ]
    
    rows = process_reports(features, "2024-01-01T12:30:00Z", "ghcnh_synop")
    assert len(rows) == 1
    row = rows[0]
    assert row["T"] == 30.0
    assert row["P"] == 1013.25
    assert row["P_type"] == "slp"
    assert row["schema_v"] == "1.0"
    assert row["station_id"] == "0-20000-0-12345"

@patch("skyguard.ingest.wis2.fetch_with_fallback")
def test_paging_and_fetch(mock_fetch):
    mock_fetch.side_effect = [
        {
            "features": [
                {
                    "properties": {
                        "wigos_station_identifier": "s1",
                        "reportId": "r1",
                        "reportTime": "2024-01-01T12:00:00Z",
                        "name": "non_coordinate_pressure",
                        "value": 100000,
                        "units": "Pa"
                    }
                }
            ],
            "links": [{"rel": "next", "href": "/collections/urn:wmo:md:in-imd:surface-based-observations.synop/items?f=json&limit=1000&cursor=abc"}]
        },
        {
            "features": [
                {
                    "properties": {
                        "wigos_station_identifier": "s2",
                        "reportId": "r2",
                        "reportTime": "2024-01-01T12:00:00Z",
                        "name": "air_temperature",
                        "value": 25.0,
                        "units": "Cel"
                    }
                }
            ],
            "links": []
        }
    ]
    
    rows = fetch_observations("2024-01-01T00:00:00Z", "2024-01-01T23:59:59Z", "ghcnh_synop")
    assert len(rows) == 2
    assert rows[0]["station_id"] == "s1"
    assert rows[0]["P_type"] == "station"
    assert rows[1]["station_id"] == "s2"
    assert rows[1]["T"] == 25.0
