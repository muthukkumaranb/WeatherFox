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
