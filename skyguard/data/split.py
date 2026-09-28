import hashlib
import json
from datetime import datetime
from pathlib import Path

def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent

def get_config():
    import tomllib
    config_path = get_base_dir() / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

def assign_split(station_id: str, ts_utc: str) -> str:
    """Return 'train', 'val' or 'test' for a given station and timestamp."""
    config = get_config().get("split", {})
    test_years = config.get("test_years", [2024])
    train_year = config.get("train_year", 2023)
    salt = config.get("station_hash_salt", "skyguard_split_v1")
    
    dt = datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ")
    
    if dt.year in test_years:
        return "test"
        
    hash_val = int(hashlib.sha256((salt + station_id).encode()).hexdigest(), 16) % 100
    
    # Hash value 0-14 (15%): test
    if hash_val < 15:
        return "test"
    # Hash value 15-29 (15%): val
    elif hash_val < 30:
        return "val"
    else:
        return "train"

def split_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """Partition rows into {'train': [...], 'val': [...], 'test': [...]}. Write split.json"""
    partitioned = {"train": [], "val": [], "test": []}
    
    stations_by_split = {"train": set(), "val": set(), "test": set()}
    periods_by_split = {"train": {"start": None, "end": None}, 
                        "val": {"start": None, "end": None}, 
                        "test": {"start": None, "end": None}}
                        
    for row in rows:
        split = assign_split(row["station_id"], row["ts_utc"])
        partitioned[split].append(row)
        stations_by_split[split].add(row["station_id"])
        
        ts = row["ts_utc"]
        p = periods_by_split[split]
        if p["start"] is None or ts < p["start"]:
            p["start"] = ts
        if p["end"] is None or ts > p["end"]:
            p["end"] = ts
            
    # Write splits
    splits_dir = get_base_dir() / "splits"
    splits_dir.mkdir(exist_ok=True)
    
    for split_name, split_rows in partitioned.items():
        with open(splits_dir / f"{split_name}.jsonl", "w") as f:
            for r in split_rows:
                f.write(json.dumps(r) + "\n")
                
    split_info = {
        "train": {"stations": sorted(list(stations_by_split["train"])), "period": periods_by_split["train"]},
        "val": {"stations": sorted(list(stations_by_split["val"])), "period": periods_by_split["val"]},
        "test": {"stations": sorted(list(stations_by_split["test"])), "period": periods_by_split["test"]}
    }
    
    canonical_json = json.dumps(split_info, sort_keys=True)
    sha256 = hashlib.sha256(canonical_json.encode()).hexdigest()
    
    with open(splits_dir / "split.json", "w") as f:
        json.dump({"splits": split_info, "sha256": sha256}, f, indent=2)
        
    return partitioned

def verify_split() -> bool:
    splits_dir = get_base_dir() / "splits"
    split_file = splits_dir / "split.json"
    if not split_file.exists():
        raise RuntimeError("split.json missing")
        
    with open(split_file, "r") as f:
        data = json.load(f)
        
    canonical_json = json.dumps(data["splits"], sort_keys=True)
    sha256 = hashlib.sha256(canonical_json.encode()).hexdigest()
    if sha256 != data["sha256"]:
        raise RuntimeError("split.json tampered")
    return True
