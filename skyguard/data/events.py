from datetime import datetime
from pathlib import Path
import json

def get_genuine_events():
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            return config.get("genuine_events", {}).get("events", [])
    except Exception:
        return []

def in_event(station_id: str, ts_utc: str, events: list, registry: dict) -> list:
    matched = []
    if station_id not in registry:
        return matched
        
    lat = registry[station_id]["lat"]
    lon = registry[station_id]["lon"]
    
    for ev in events:
        if ev["start"] <= ts_utc <= ev["end"]:
            if ev["lat_min"] <= lat <= ev["lat_max"] and ev["lon_min"] <= lon <= ev["lon_max"]:
                matched.append(ev)
    return matched

def mark_genuine_events(rows: list[dict], registry: dict[str, dict]) -> list[dict]:
    """Annotate rows that fall inside a genuine-event window.
    Returns a list of event descriptors."""
    events = get_genuine_events()
    matched_events = []
    
    # Write labels
    labels_dir = Path(__file__).resolve().parent.parent.parent / "data" / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    
    with open(labels_dir / "events.jsonl", "w") as f:
        for row in rows:
            evs = in_event(row["station_id"], row["ts_utc"], events, registry)
            if evs:
                matched_events.extend([{
                    "station_id": row["station_id"],
                    "start": e["start"],
                    "end": e["end"],
                    "type": e["type"],
                    "name": e["name"]
                } for e in evs])
                
                f.write(json.dumps({
                    "station_id": row["station_id"],
                    "ts_utc": row["ts_utc"],
                    "events": [e["name"] for e in evs]
                }) + "\n")
                
    # deduplicate matched events
    unique_events = []
    seen = set()
    for m in matched_events:
        k = (m["station_id"], m["name"])
        if k not in seen:
            seen.add(k)
            unique_events.append(m)
            
    return unique_events
