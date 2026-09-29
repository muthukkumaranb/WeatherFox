import hashlib
import json
from datetime import datetime
from pathlib import Path

def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent

_cached_config = None
def get_config():
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    import tomllib
    config_path = get_base_dir() / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            _cached_config = tomllib.load(f)
            return _cached_config
    except Exception:
        _cached_config = {}
        return _cached_config

_hash_cache = {}

def assign_split(station_id: str, ts_utc: str) -> str:
    """Return 'train', 'val' or 'test' for a given station and timestamp."""
    config = get_config().get("split", {})
    test_years = config.get("test_years", [2024])
    train_year = config.get("train_year", 2023)
    salt = config.get("station_hash_salt", "skyguard_split_v1")
    
    yr_str = ts_utc[:4]
    try:
        yr = int(yr_str)
        if yr in test_years:
            return "test"
    except Exception:
        pass
        
    if station_id not in _hash_cache:
        hash_val = int(hashlib.sha256((salt + station_id).encode()).hexdigest(), 16) % 100
        _hash_cache[station_id] = hash_val
    else:
        hash_val = _hash_cache[station_id]
        
    # Hash value 0-14 (15%): test
    if hash_val < 15:
        return "test"
    # Hash value 15-21 (~7.5%): val_cal
    elif hash_val < 22:
        return "val_cal"
    # Hash value 22-29 (~7.5%): val_eval
    elif hash_val < 30:
        return "val_eval"
    else:
        return "train"

def split_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """Partition rows into {'train': [...], 'val_cal': [...], 'val_eval': [...], 'test': [...]}. Write split.json"""
    partitioned = {"train": [], "val_cal": [], "val_eval": [], "test": []}
    
    stations_by_split = {"train": set(), "val_cal": set(), "val_eval": set(), "test": set()}
    periods_by_split = {"train": {"start": None, "end": None}, 
                        "val_cal": {"start": None, "end": None}, 
                        "val_eval": {"start": None, "end": None}, 
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
            chunk = []
            for r in split_rows:
                chunk.append(json.dumps(r))
                if len(chunk) > 20000:
                    f.write("\n".join(chunk) + "\n")
                    chunk.clear()
            if chunk:
                f.write("\n".join(chunk) + "\n")
                
    split_info = {
        "train": {"stations": sorted(list(stations_by_split["train"])), "period": periods_by_split["train"]},
        "val_cal": {"stations": sorted(list(stations_by_split["val_cal"])), "period": periods_by_split["val_cal"]},
        "val_eval": {"stations": sorted(list(stations_by_split["val_eval"])), "period": periods_by_split["val_eval"]},
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
