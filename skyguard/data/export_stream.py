import json
import random
import math
from pathlib import Path
from datetime import datetime, timedelta

from skyguard.contract import validate_input_row

def stream_rows(data_dir: str, *, station_ids: list[str] = None) -> list[dict]:
    """Yield contract input-row dicts in chronological order."""
    import pandas as pd
    
    clean_obs_dir = Path(data_dir) / "clean" / "obs"
    if not clean_obs_dir.exists():
        return []
        
    all_rows = []
    
    for pq_file in clean_obs_dir.glob("*.parquet"):
        sid = pq_file.stem
        if station_ids and sid not in station_ids:
            continue
            
        df = pd.read_parquet(pq_file)
        # convert df back to dicts
        for record in df.to_dict("records"):
            # nan to none
            for k, v in record.items():
                if isinstance(v, float) and math.isnan(v):
                    record[k] = None
            all_rows.append(record)
            
    all_rows.sort(key=lambda r: r.get("ingest_ts_utc", r.get("ts_utc")))
    
    # validate
    valid = []
    for r in all_rows:
        try:
            validate_input_row(r)
            valid.append(r)
        except Exception:
            pass
            
    return valid

def fabricate_ingest(rows: list[dict], seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    station_seq = {}
    
    for r in rows:
        sid = r["station_id"]
        station_seq[sid] = station_seq.get(sid, 0) + 1
        r["seq"] = station_seq[sid]
        
        ts_str = r["ts_utc"]
        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
        
        # lognormal delay median 90s
        delay = int(rng.lognormvariate(math.log(90), 0.5))
        ingest_dt = dt + timedelta(seconds=delay)
        r["ingest_ts_utc"] = ingest_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        
    return rows
