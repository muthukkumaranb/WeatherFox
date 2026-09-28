import pytest
from skyguard.data.clean import dedup_metar_synop, clean_rows, snap_to_grid
from skyguard.data.split import assign_split, verify_split, split_rows
from skyguard.data.events import in_event
from skyguard.contract import validate_input_row
import json

def test_dedup_keeps_synop_over_metar():
    rows = [
        {"station_id": "A", "ts_utc": "2023-01-01T00:00:00Z", "source": "ghcnh_metar", "T": 25.0},
        {"station_id": "A", "ts_utc": "2023-01-01T00:00:00Z", "source": "ghcnh_synop", "T": 25.1}
    ]
    res = dedup_metar_synop(rows)
    assert len(res) == 1
    assert res[0]["source"] == "ghcnh_synop"
    assert res[0]["T"] == 25.1

def test_clean_rows_flags_bad_qc():
    rows = [
        {"station_id": "A", "T": 20.0, "qc": {"T": "1"}}, # common
        {"station_id": "A", "T": 21.0, "qc": {"T": "1"}},
        {"station_id": "A", "T": 22.0, "qc": {"T": "X"}}  # bad, not in pass list
    ]
    res = clean_rows(rows)
    assert res[0]["T"] == 20.0
    assert res[1]["T"] == 21.0
    assert res[2]["T"] is None

def test_snap_to_grid_no_reuse():
    rows = [
        {"station_id": "A", "ts_utc": "2023-01-01T00:15:00Z", "cadence_min": 60, "val": 1},
        {"station_id": "A", "ts_utc": "2023-01-01T00:45:00Z", "cadence_min": 60, "val": 2}
    ]
    # grid points: 00:00 and 01:00
    res = snap_to_grid(rows, tolerance_min=30)
    assert len(res) == 2
    assert res[0]["ts_utc"] == "2023-01-01T00:00:00Z"
    assert res[0]["val"] == 1
    assert res[1]["ts_utc"] == "2023-01-01T01:00:00Z"
    assert res[1]["val"] == 2

def test_split_hash_tampering(tmp_path, monkeypatch):
    import skyguard.data.split
    # mock get_base_dir to tmp_path
    monkeypatch.setattr("skyguard.data.split.get_base_dir", lambda: tmp_path)
    
    rows = [{"station_id": "INI0001", "ts_utc": "2023-01-01T00:00:00Z"}]
    split_rows(rows)
    
    assert verify_split() is True
    
    # tamper
    split_file = tmp_path / "splits" / "split.json"
    data = json.loads(split_file.read_text())
    data["splits"]["train"]["stations"].append("FAKE")
    split_file.write_text(json.dumps(data))
    
    with pytest.raises(RuntimeError, match="tampered"):
        verify_split()

def test_exported_rows_contract_valid():
    from skyguard.data.download import parse_to_rows
    from tests.fixtures.make_fake_ghcnh import create_fake_ghcnh
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_dir = create_fake_ghcnh(Path(tmp_dir))
        for psv in raw_dir.glob("*.psv"):
            rows = parse_to_rows(str(psv))
            for r in rows:
                validate_input_row(r)

def test_event_membership():
    events = [{
        "name": "test_event", "type": "heat_wave",
        "start": "2023-01-01T00:00:00Z", "end": "2023-01-02T00:00:00Z",
        "lat_min": 10.0, "lat_max": 20.0,
        "lon_min": 70.0, "lon_max": 80.0
    }]
    registry = {"A": {"lat": 15.0, "lon": 75.0}}
    
    res = in_event("A", "2023-01-01T12:00:00Z", events, registry)
    assert len(res) == 1
    assert res[0]["name"] == "test_event"
    
    res_outside = in_event("A", "2023-01-03T12:00:00Z", events, registry)
    assert len(res_outside) == 0
