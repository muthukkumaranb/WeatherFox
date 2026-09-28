import collections
import math
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

def get_config():
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

def dedup_metar_synop(rows: list[dict]) -> list[dict]:
    """Remove METAR duplicates when a SYNOP exists at the same timestamp."""
    grouped = collections.defaultdict(list)
    for r in rows:
        ts = r.get("ts_utc")
        if ts:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            # rounded to nearest 30 min
            mins = (dt.minute // 30) * 30
            dt_rounded = dt.replace(minute=mins, second=0)
            grouped[(r["station_id"], dt_rounded)].append(r)
            
    deduped = []
    for k, grp in grouped.items():
        if len(grp) == 1:
            deduped.append(grp[0])
            continue
            
        synops = [r for r in grp if r.get("source") == "ghcnh_synop"]
        if synops:
            deduped.append(synops[0]) # keep synop
        else:
            # multiple metars, keep one with most non-null readings
            def count_non_null(r):
                return sum(1 for var in ("T", "Td", "RH", "P") if r.get(var) is not None)
            best = max(grp, key=count_non_null)
            deduped.append(best)
            
    # return sorted by ts_utc
    return sorted(deduped, key=lambda r: r.get("ts_utc", ""))

def snap_to_grid(rows: list[dict], tolerance_min: int = 30) -> list[dict]:
    """Snap rows to a regular time grid within *tolerance_min* minutes."""
    if not rows:
        return []
        
    cadence = rows[0].get("cadence_min", 60)
    
    # build grid
    grid_rows = []
    used = set()
    
    # Find start and end times
    times = [datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") for r in rows if r.get("ts_utc")]
    if not times:
        return []
        
    start_dt = min(times).replace(minute=0, second=0)
    end_dt = max(times).replace(minute=0, second=0) + timedelta(hours=1)
    
    grid_times = []
    curr = start_dt
    while curr <= end_dt:
        grid_times.append(curr)
        curr += timedelta(minutes=cadence)
        
    for gt in grid_times:
        best_r = None
        best_diff = float("inf")
        best_idx = -1
        
        for i, r in enumerate(rows):
            if i in used:
                continue
            rt = datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
            diff_min = abs((rt - gt).total_seconds()) / 60.0
            if diff_min <= tolerance_min and diff_min < best_diff:
                best_diff = diff_min
                best_r = r
                best_idx = i
                
        if best_r:
            new_r = best_r.copy()
            new_r["ts_utc"] = gt.strftime("%Y-%m-%dT%H:%M:%SZ")
            grid_rows.append(new_r)
            used.add(best_idx)
            
    return grid_rows

def assign_cadence(rows: list[dict]) -> list[dict]:
    """Compute and assign ``cadence_min`` for each station's rows."""
    if len(rows) < 2:
        for r in rows:
            r["cadence_min"] = 60
        return rows
        
    times = [datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") for r in rows if r.get("ts_utc")]
    diffs = [(times[i+1] - times[i]).total_seconds() / 60.0 for i in range(len(times)-1)]
    
    if not diffs:
        med = 60
    else:
        diffs.sort()
        med = diffs[len(diffs) // 2]
        
    # round to 1, 15, 30, 60, 180
    cands = [1, 15, 30, 60, 180]
    cadence = min(cands, key=lambda x: abs(x - med))
    
    for r in rows:
        r["cadence_min"] = cadence
        
    return rows

def clean_rows(rows: list[dict]) -> list[dict]:
    config = get_config().get("clean", {})
    extra_pass_codes = config.get("extra_pass_codes", ["0", "1", "4", "5", "9", "A", "U", "P", "I", "M", "C", "R"])
    t_min = config.get("T_min", -40.0)
    t_max = config.get("T_max", 60.0)
    td_min = config.get("Td_min", -60.0)
    td_max = config.get("Td_max", 40.0)
    p_min = config.get("P_min", 850.0)
    p_max = config.get("P_max", 1085.0)
    
    # 1. QC flagging
    qc_counts = {"T": collections.Counter(), "Td": collections.Counter(), "RH": collections.Counter(), "P": collections.Counter()}
    for r in rows:
        qc = r.get("qc", {})
        for k in qc_counts:
            if qc.get(k):
                qc_counts[k][qc[k]] += 1
                
    most_common_qc = {}
    for k, c in qc_counts.items():
        if c:
            most_common_qc[k] = c.most_common(1)[0][0]
            
    cleaned = []
    for r in rows:
        qc = r.get("qc", {})
        for var in ("T", "Td", "RH", "P"):
            val = r.get(var)
            q = qc.get(var)
            
            if val is not None:
                if q and q != most_common_qc.get(var) and q not in extra_pass_codes:
                    r[var] = None
                else:
                    # Gross limits
                    if var == "T" and (val < t_min or val > t_max):
                        r[var] = None
                    elif var == "Td" and (val < td_min or val > td_max):
                        r[var] = None
                    elif var == "P" and (val < p_min or val > p_max):
                        r[var] = None
                        
        # compute RH from T, Td if missing
        if r.get("RH") is None and r.get("T") is not None and r.get("Td") is not None:
            t = r["T"]
            td = r["Td"]
            # Magnus formula
            try:
                e = 6.112 * math.exp((17.625 * td) / (243.04 + td))
                es = 6.112 * math.exp((17.625 * t) / (243.04 + t))
                rh = 100.0 * (e / es)
                r["RH"] = max(0.0, min(100.0, rh))
            except Exception:
                pass
                
        cleaned.append(r)
        
    return cleaned

def clean_station(station_id: str, raw_rows: list[dict], data_dir: str):
    rows = clean_rows(raw_rows)
    rows = assign_cadence(rows)
    obs_rows = dedup_metar_synop(rows)
    
    grid_rows = snap_to_grid(obs_rows, tolerance_min=30)
    
    clean_dir = Path(data_dir) / "clean"
    (clean_dir / "obs").mkdir(parents=True, exist_ok=True)
    (clean_dir / "grid").mkdir(parents=True, exist_ok=True)
    
    df_obs = pd.DataFrame(obs_rows)
    df_grid = pd.DataFrame(grid_rows)
    
    if not df_obs.empty:
        df_obs.to_parquet(clean_dir / "obs" / f"{station_id}.parquet")
    if not df_grid.empty:
        df_grid.to_parquet(clean_dir / "grid" / f"{station_id}.parquet")
        
    return obs_rows, grid_rows
