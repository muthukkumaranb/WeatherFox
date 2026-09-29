import collections
import math
import calendar
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

def fast_epoch(ts: str) -> int:
    """Fast parse %Y-%m-%dT%H:%M:%SZ to epoch seconds."""
    # "2024-01-01T12:30:00Z"
    y = int(ts[0:4])
    m = int(ts[5:7])
    d = int(ts[8:10])
    h = int(ts[11:13])
    mn = int(ts[14:16])
    s = int(ts[17:19])
    # simplified, using calendar.timegm
    return calendar.timegm((y, m, d, h, mn, s))

def dedup_metar_synop(rows: list[dict]) -> list[dict]:
    """Remove METAR duplicates when a SYNOP exists at the same timestamp."""
    grouped = collections.defaultdict(list)
    for r in rows:
        ts = r.get("ts_utc")
        if ts:
            # round to nearest 30 min
            mins = fast_epoch(ts) / 60.0
            rounded_mins = round(mins / 30.0) * 30
            grouped[(r["station_id"], rounded_mins)].append(r)
            
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
    
    grid_map = {}
    for r in rows:
        ts = r.get("ts_utc")
        if not ts:
            continue
        mins = fast_epoch(ts) / 60.0
        grid_m = round(mins / cadence) * cadence
        diff = abs(mins - grid_m)
        if diff <= tolerance_min:
            if grid_m not in grid_map or diff < grid_map[grid_m][0]:
                grid_map[grid_m] = (diff, r)
                
    grid_rows = []
    for gm in sorted(grid_map.keys()):
        new_r = grid_map[gm][1].copy()
        gt = datetime.utcfromtimestamp(gm * 60)
        new_r["ts_utc"] = gt.strftime("%Y-%m-%dT%H:%M:%SZ")
        grid_rows.append(new_r)
        
    return grid_rows

def assign_cadence(rows: list[dict]) -> list[dict]:
    """Compute and assign ``cadence_min`` for each station's rows."""
    if len(rows) < 2:
        for r in rows:
            r["cadence_min"] = 60
        return rows
        
    times = [fast_epoch(r["ts_utc"]) for r in rows if r.get("ts_utc")]
    diffs = [(times[i+1] - times[i]) / 60.0 for i in range(len(times)-1)]
    
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
                    if var == "T" and (val < t_min or val > t_max):
                        r[var] = None
                    elif var == "Td" and (val < td_min or val > td_max):
                        r[var] = None
                    elif var == "P" and (val < p_min or val > p_max):
                        r[var] = None
                        
        if r.get("RH") is None and r.get("T") is not None and r.get("Td") is not None:
            t = r["T"]
            td = r["Td"]
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
    
    return obs_rows, grid_rows
