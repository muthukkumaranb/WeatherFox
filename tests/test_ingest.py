"""Tests for skyguard.ingest (rule_gate, rules, buffers, replay).

Run with: python -m pytest -q
"""
import copy
import json
import time
from pathlib import Path

import pytest

from skyguard.contract import ContractError, validate_verdict
from skyguard.ingest.buffers import BufferPool, StationBuffer
from skyguard.ingest.replay import (
    build_synthetic_registry, generate_synthetic_stream, load_replay_stream, replay,
)
from skyguard.ingest.rule_gate import check as rule_gate_check
from skyguard.ingest.rules import (
    build_comms_gap_verdict, build_duplicate_verdict, detect_comms_gap,
    detect_duplicate, detect_timeshift,
)

EX = Path(__file__).resolve().parent.parent / "examples"


def load_example(name: str = "input_row.json") -> dict:
    return json.loads((EX / name).read_text())


# ---------------------------------------------------------------------------
# rule_gate tests
# ---------------------------------------------------------------------------

def test_rule_gate_gross_range():
    row_normal = load_example("input_row.json")
    res = rule_gate_check([row_normal])
    assert res["T"]["fail"] is False
    assert res["RH"]["fail"] is False
    assert res["P"]["fail"] is False

    row_bad_t = copy.deepcopy(row_normal)
    row_bad_t["T"] = 65.0  # > 60
    res = rule_gate_check([row_bad_t])
    assert res["T"]["fail"] is True
    assert res["T"]["cause"] == "out_of_range"

    row_bad_rh = copy.deepcopy(row_normal)
    row_bad_rh["RH"] = 110.0  # > 103
    res = rule_gate_check([row_bad_rh])
    assert res["RH"]["fail"] is True
    assert res["RH"]["cause"] == "out_of_range"

    row_bad_p = copy.deepcopy(row_normal)
    row_bad_p["P"] = 550.0  # < 600
    res = rule_gate_check([row_bad_p])
    assert res["P"]["fail"] is True
    assert res["P"]["cause"] == "out_of_range"


def test_rule_gate_step_limit_is_suspect_not_fail():
    r1 = load_example("input_row.json")
    r1["ts_utc"] = "2026-09-28T00:00:00Z"
    r2 = copy.deepcopy(r1)
    r2["ts_utc"] = "2026-09-28T00:30:00Z"
    r2["T"] += 7.0
    res = rule_gate_check([r1, r2], cadence_min=30)
    assert res["T"]["fail"] is False
    assert res["T"]["suspect"] is True
    assert res["T"]["cause"] == "spike"


def test_rule_gate_short_metar_series_not_frozen():
    r = load_example("input_row.json")
    r["source"] = "ghcnh_metar"
    r["T"] = 25.0
    rows = []
    for i in range(4):
        rc = copy.deepcopy(r)
        rc["ts_utc"] = f"2026-09-28T00:{i * 10:02d}:00Z"
        rows.append(rc)

    res = rule_gate_check(rows, cadence_min=10)
    assert res["T"]["suspect"] is False
    assert res["T"]["fail"] is False


def test_rule_gate_13h_metar_series_is_suspect():
    r = load_example("input_row.json")
    r["source"] = "ghcnh_metar"
    r["T"] = 25.0
    rows = []
    for i in range(14):
        rc = copy.deepcopy(r)
        rc["ts_utc"] = f"2026-09-28T{i:02d}:00:00Z"
        rows.append(rc)

    res = rule_gate_check(rows, cadence_min=60)
    assert res["T"]["fail"] is False
    assert res["T"]["suspect"] is True
    assert res["T"]["cause"] == "frozen"


def test_rule_gate_fog_night_not_frozen():
    r = load_example("input_row.json")
    r["source"] = "ghcnh_synop"
    r["T"] = 20.0
    r["Td"] = 19.8
    r["RH"] = 99.0
    rows = []
    for i in range(14):
        rc = copy.deepcopy(r)
        rc["ts_utc"] = f"2026-09-28T{i:02d}:00:00Z"
        rows.append(rc)

    res = rule_gate_check(rows, cadence_min=60)
    assert res["T"]["suspect"] is False
    assert res["RH"]["suspect"] is False
    assert res["T"]["fail"] is False
    assert res["RH"]["fail"] is False


def test_rule_gate_dewpoint_limit():
    r = load_example("input_row.json")
    r["T"] = 25.0
    r["Td"] = 26.0  # Td > T + 0.2
    res = rule_gate_check([r])
    assert res["RH"]["fail"] is True
    assert res["RH"]["cause"] == "out_of_range"


# ---------------------------------------------------------------------------
# rules tests
# ---------------------------------------------------------------------------

def test_detect_duplicate_and_verdict():
    r1 = load_example("input_row.json")
    r2 = copy.deepcopy(r1)  # copy with same seq/timestamp
    rows = [r1, r2]

    dups = detect_duplicate(rows)
    assert dups == [1]

    v = build_duplicate_verdict(r2)
    assert v["label"] == "uncertain"
    assert v["vars"]["T"]["root_cause"] == "duplicate"
    validate_verdict(v)


def test_detect_timeshift_and_comms_gap():
    r1 = load_example("input_row.json")
    r1["ts_utc"] = "2026-09-28T00:00:00Z"
    r1["ingest_ts_utc"] = "2026-09-28T02:00:00Z"  # 120 min diff > 30 min tolerance

    shifted = detect_timeshift([r1], tolerance_min=30)
    assert shifted == [0]

    v_gap = build_comms_gap_verdict("INI0001", "2026-09-28T03:00:00Z")
    assert v_gap["vars"]["T"]["root_cause"] == "comms_gap"
    validate_verdict(v_gap)


# ---------------------------------------------------------------------------
# buffers tests
# ---------------------------------------------------------------------------

def test_station_buffer_ring_eviction():
    buf = StationBuffer(max_rows=3)
    r = load_example("input_row.json")

    for i in range(5):
        row = copy.deepcopy(r)
        row["seq"] = i
        buf.push(row)

    assert len(buf) == 3
    window = buf.window()
    assert [x["seq"] for x in window] == [2, 3, 4]


def test_buffer_pool():
    pool = BufferPool(max_rows_per_station=10)
    r1 = load_example("input_row.json")
    r1["station_id"] = "ST1"
    r2 = copy.deepcopy(r1)
    r2["station_id"] = "ST2"

    pool.push(r1)
    pool.push(r2)

    assert set(pool.get_all_station_ids()) == {"ST1", "ST2"}
    assert len(pool.window("ST1")) == 1
    assert len(pool.window("ST2")) == 1


# ---------------------------------------------------------------------------
# replay tests
# ---------------------------------------------------------------------------

def test_replay_synthetic_stream():
    stream = generate_synthetic_stream(num_stations=6, num_clusters=2, rows_per_station=3)
    registry = build_synthetic_registry(num_stations=6, num_clusters=2)

    received_verdicts = []

    def cb(v):
        received_verdicts.append(v)

    verdicts = replay(stream, registry=registry, callback=cb)
    assert len(verdicts) == 18
    assert len(received_verdicts) == 18
    for v in verdicts:
        validate_verdict(v)


def test_replay_drops_duplicates():
    r1 = load_example("input_row.json")
    r2_inexact = copy.deepcopy(r1)  # duplicate ts with differing T value
    r2_inexact["T"] = 35.0
    r3 = copy.deepcopy(r1)
    r3["seq"] += 1
    r3["ts_utc"] = "2026-09-28T06:15:00Z"

    verdicts = replay([r1, r2_inexact, r3])
    # r2_inexact is inexact duplicate -> emits duplicate verdict
    assert any(v.get("vars", {}).get("T", {}).get("root_cause") == "duplicate" for v in verdicts)



def test_replay_window_always_contains_target():
    stream = generate_synthetic_stream(num_stations=4, rows_per_station=2)
    custom_windows = []

    def mock_scorer(station_window, target):
        assert target in station_window
        assert len(station_window[target]) > 0
        custom_windows.append((target, list(station_window.keys())))
        # build simple verdict
        return {
            "schema_v": "1.0",
            "station_id": target,
            "ts_utc": station_window[target][-1]["ts_utc"],
            "phase": "final",
            "label": "normal",
            "model_version": "test-1.0",
            "spatial_support": "neighbours_normal",
            "n_neighbours": len(station_window) - 1,
            "genuine_event": False,
            "vars": {
                "T": {"label": "normal", "confidence": 0.99},
                "RH": {"label": "normal", "confidence": 0.99},
                "P": {"label": "normal", "confidence": 0.99},
            },
        }

    verdicts = replay(stream, scorer=mock_scorer)
    assert len(verdicts) == 8
    assert len(custom_windows) == 8


def test_replay_speed_factor():
    stream = generate_synthetic_stream(num_stations=2, rows_per_station=3)
    start_t = time.perf_counter()
    replay(stream, speed_factor=100.0)  # fast simulation
    elapsed = time.perf_counter() - start_t
    assert elapsed < 2.0  # completes quickly


def test_mumbai_station_longitude_radiation():
    from skyguard.fake_score import score
    # Mumbai station (lon 72.8777). At 01:25 UTC, solar_hour is ~6.27 (sun_factor ~0.07 < 0.1, night/dawn in Mumbai),
    # whereas at Delhi (lon 77.2), solar_hour is ~6.56 (sun_factor ~0.15 > 0.1, daytime).
    registry = {
        "BOM0001": {"lat": 19.0760, "lon": 72.8777, "elevation": 10.0},
        "BOM0002": {"lat": 19.0800, "lon": 72.8800, "elevation": 10.0},
    }
    # Neighbor temp is 25.0, target temp is 30.0 (diff = +5.0)
    target_row1 = {
        "schema_v": "1.0",
        "station_id": "BOM0001",
        "ts_utc": "2026-09-28T03:00:00Z",
        "ingest_ts_utc": "2026-09-28T03:00:00Z",
        "seq": 1,
        "T": 30.0,
        "Td": 20.0,
        "RH": 55.0,
        "P": 1013.2,
        "P_type": "slp",
        "cadence_min": 15,
        "source": "ghcnh_synop",
    }
    target_row2 = copy.deepcopy(target_row1)
    target_row2["ts_utc"] = "2026-09-28T04:00:00Z"
    target_row2["seq"] = 2

    nb_row1 = copy.deepcopy(target_row1)
    nb_row1["station_id"] = "BOM0002"
    nb_row1["T"] = 25.0
    nb_row2 = copy.deepcopy(target_row2)
    nb_row2["station_id"] = "BOM0002"
    nb_row2["T"] = 25.0

    # 1. At 01:25:00Z for Mumbai (lon 72.8777), solar_hour is ~6.27 (sun_factor ~0.07 <= 0.3), so radiation is not triggered
    mumbai_night_row = copy.deepcopy(target_row1)
    mumbai_night_row["ts_utc"] = "2026-09-28T01:25:00Z"
    v_mumbai = score({"BOM0001": [mumbai_night_row], "BOM0002": [nb_row1]}, "BOM0001", registry=registry)
    assert v_mumbai["vars"]["T"].get("root_cause") != "radiation"

    # 2. For Delhi (lon 77.2), at 04:00 UTC (with rows at 03:00 and 04:00 UTC), sun_factor > 0.3 over 2 consecutive readings, triggering radiation
    v_delhi = score({"BOM0001": [target_row1, target_row2], "BOM0002": [nb_row1, nb_row2]}, "BOM0001", registry={"BOM0001": {"lon": 77.2}})
    assert v_delhi["vars"]["T"].get("root_cause") == "radiation"



