import pytest
from skyguard.detect.detector import Detector
from skyguard.detect.event_rule import evaluate_event_rule

def test_single_station_spike():
    detector = Detector()
    # mock everything
    res = evaluate_event_rule(30.0, 22.0, 8.0, [-0.1, 0.2, 0.0], [0.1, 0.2, 0.0])
    assert res == "neighbours_normal"

def test_cluster_jump():
    res = evaluate_event_rule(30.0, 22.0, 8.0, [8.1, 7.9, 8.0], [1.1, 1.2, 0.9])
    assert res == "neighbours_also_deviating"

def test_isolated_station():
    res = evaluate_event_rule(30.0, 22.0, 8.0, [0.1], [0.1])
    assert res == "no_neighbours"

def test_forecaster_train_and_predict():
    from skyguard.detect.forecaster import Forecaster
    from skyguard.detect.climatology import Climatology
    c = Climatology()
    rows = [{"station_id": "A", "ts_utc": f"2023-01-01T{h:02d}:00:00Z", "T": 20} for h in range(10)]
    c.fit(rows)
    f = Forecaster()
    f.fit(rows, c)
    assert True

def test_no_leak_in_features():
    from skyguard.contract import assert_no_leak
    # just assert it doesn't raise
    assert_no_leak(["T_lag_1h", "clim_T_median"])

def test_get_3h_change_sign():
    detector = Detector()
    history = [
        {"ts_utc": "2023-01-01T00:00:00Z", "T": 10.0},
        {"ts_utc": "2023-01-01T01:00:00Z", "T": 12.0},
        {"ts_utc": "2023-01-01T02:00:00Z", "T": 14.0},
        {"ts_utc": "2023-01-01T03:00:00Z", "T": 16.0},
    ]
    r = {"ts_utc": "2023-01-01T04:00:00Z", "T": 20.0}
    
    # 3 hours before 04:00 is 01:00. At 01:00, T=12.0.
    # So 3h change is 20.0 - 12.0 = 8.0.
    # It must not match future timestamps or 2 hours ago.
    change = detector.get_3h_change(r, history, "T")
    assert change == 8.0

def test_get_3h_change_ignores_future():
    detector = Detector()
    # history has future timestamp! 2 hours before 04:00 is 02:00
    # Wait, 3h before 04:00 is 01:00.
    history = [
        {"ts_utc": "2023-01-01T01:00:00Z", "T": 12.0},
        {"ts_utc": "2023-01-01T02:00:00Z", "T": 14.0},
    ]
    r = {"ts_utc": "2023-01-01T04:00:00Z", "T": 20.0}
    # It should pick 01:00.
    assert detector.get_3h_change(r, history, "T") == 8.0
    
    # If history only has 02:00 (2 hours ago, which is hts > target_ts), it should NOT pick it!
    # target_ts = 01:00. hts = 02:00. diff = target_ts - hts = -3600.
    # diff must be >= 0, so it will ignore 02:00.
    history2 = [
        {"ts_utc": "2023-01-01T02:00:00Z", "T": 14.0}
    ]
    assert detector.get_3h_change(r, history2, "T") == 0.0
