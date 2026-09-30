"""A simulated storm must reach the scorer as plain weather data: no ground-truth tags in the rows.
The scorer has to infer "genuine event" from neighbours moving together."""
from skyguard.api import main as api
from skyguard.ingest.replay import build_synthetic_registry, generate_synthetic_stream
from skyguard.scorer import score

CLUSTER = ["INI0005", "INI0006", "INI0007", "INI0008"]  # Mumbai, Thane, Pune, Nashik
TAG_KEYS = {"genuine_event", "is_genuine_event", "injected", "is_injected"}


def _history(hours: int = 72) -> dict[str, list[dict]]:
    rows = generate_synthetic_stream(num_stations=16, rows_per_station=hours)
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r["station_id"] in CLUSTER:
            by.setdefault(r["station_id"], []).append(dict(r))
    return by


def test_storm_rows_carry_no_tags_and_are_detected_from_data():
    api.state.reset()
    try:
        by = _history()
        api.state.active_events = [{
            "station_id": "INI0007", "kind": "heat_wave", "duration_hours": 12.0, "hours_done": 0.0,
            "affected_stations": CLUSTER,
        }]
        # Apply the storm to the last 4 hours of every cluster station, hour by hour.
        n = len(by["INI0007"])
        for i in range(n - 4, n):
            for sid in CLUSTER:
                by[sid][i] = api.apply_event_injections(by[sid][i])
        for sid in CLUSTER:
            for r in by[sid]:
                assert not (TAG_KEYS & r.keys()), f"ground-truth tag leaked into scorer input: {TAG_KEYS & r.keys()}"
        registry = build_synthetic_registry()
        verdicts = [score({s: by[s] for s in CLUSTER}, t, registry=registry) for t in CLUSTER]
        assert all(v["label"] == "normal" for v in verdicts), [v["vars"]["T"] for v in verdicts]
        assert sum(v["genuine_event"] for v in verdicts) >= 3
    finally:
        api.state.reset()


def test_event_clock_follows_reading_time_for_all_stations():
    """Every station of the cluster sees the same event hours; none is dropped mid-hour."""
    api.state.reset()
    try:
        by = _history(30)
        api.state.active_events = [{
            "station_id": "INI0007", "kind": "heat_wave", "duration_hours": 3.0, "hours_done": 0.0,
            "affected_stations": CLUSTER,
        }]
        for i in range(20, 30):
            for sid in CLUSTER:
                api.apply_event_injections(by[sid][i])
        hours_by_station = {
            sid: sorted(ts for (s, ts) in api.state.event_keys if s == sid) for sid in CLUSTER
        }
        first = hours_by_station[CLUSTER[0]]
        assert len(first) == 3
        assert all(h == first for h in hours_by_station.values())
    finally:
        api.state.reset()
