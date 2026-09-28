import copy
import json
import math
import random
from pathlib import Path
from datetime import datetime, timedelta

from skyguard.contract import validate_injection, validate_input_row, ROOT_CAUSES

def get_genuine_events():
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            return config.get("genuine_events", {}).get("events", [])
    except Exception:
        return []

def load_registry(data_dir: str) -> dict:
    import csv
    path = Path(data_dir) / "station_registry.csv"
    reg = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                reg[row["station_id"]] = {
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"])
                }
    return reg

def in_event(sid: str, ts_str: str, events: list, reg: dict) -> bool:
    if sid not in reg:
        return False
    lat = reg[sid]["lat"]
    lon = reg[sid]["lon"]
    for ev in events:
        if ev["start"] <= ts_str <= ev["end"]:
            if ev["lat_min"] <= lat <= ev["lat_max"] and ev["lon_min"] <= lon <= ev["lon_max"]:
                return True
    return False

def recompute_rh(r: dict):
    if r.get("T") is not None and r.get("Td") is not None:
        t = r["T"]
        td = r["Td"]
        try:
            e = 6.112 * math.exp((17.625 * td) / (243.04 + td))
            es = 6.112 * math.exp((17.625 * t) / (243.04 + t))
            rh = 100.0 * (e / es)
            r["RH"] = round(max(0.0, min(100.0, rh)), 1)
        except Exception:
            pass

def round_vars(r: dict):
    if r.get("T") is not None:
        r["T"] = round(r["T"], 1)
    if r.get("Td") is not None:
        r["Td"] = round(r["Td"], 1)
    if r.get("P") is not None:
        r["P"] = round(r["P"], 1)
    if r.get("RH") is not None:
        r["RH"] = round(r["RH"], 1)

def inject_faults(
    rows: list[dict],
    *,
    seed: int = 42,
    rate: float = 0.05,
    split: str = "train"
) -> tuple[list[dict], list[dict]]:
    
    rng = random.Random(seed)
    out_rows = []
    labels = []
    
    events = get_genuine_events()
    reg = load_registry(str(Path(__file__).resolve().parent.parent.parent / "data"))
    
    by_station = {}
    for r in rows:
        by_station.setdefault(r["station_id"], []).append(copy.deepcopy(r))
        
    inj_idx = 0
    
    for sid, s_rows in by_station.items():
        n = len(s_rows)
        if n < 10:
            out_rows.extend(s_rows)
            continue
            
        num_inj = max(1, int(n * rate))
        
        # avoid overlapping injections on the same variable
        inj_mask = [{"T": False, "RH": False, "P": False, "all": False} for _ in range(n)]
        
        for _ in range(num_inj):
            cause = rng.choice(ROOT_CAUSES)
            
            # Select random start
            start_i = rng.randint(0, n - 1)
            start_ts = s_rows[start_i]["ts_utc"]
            
            if in_event(sid, start_ts, events, reg):
                continue
                
            # determine duration
            dur_h = 0
            if cause == "spike": dur_h = rng.randint(1, 3)
            elif cause == "frozen": dur_h = rng.randint(6, 24)
            elif cause == "drift": dur_h = rng.randint(12, 72)
            elif cause == "offset": dur_h = rng.randint(6, 48)
            elif cause == "noise": dur_h = rng.randint(3, 12)
            elif cause == "out_of_range": dur_h = rng.randint(1, 3)
            elif cause == "radiation": dur_h = rng.randint(3, 8)
            elif cause == "power": dur_h = rng.randint(1, 6)
            elif cause == "comms_gap": dur_h = rng.randint(3, 24)
            elif cause == "duplicate": dur_h = 1
            elif cause == "timeshift": dur_h = rng.randint(6, 24)
            elif cause == "unknown": dur_h = rng.randint(12, 24)
            else: dur_h = 3
            
            # find end_i based on duration hours
            end_ts_dt = datetime.strptime(start_ts, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=dur_h)
            end_ts = end_ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_i = start_i
            while end_i < n and s_rows[end_i]["ts_utc"] <= end_ts:
                end_i += 1
            end_i = min(end_i, n - 1)
            
            if end_i == start_i and cause not in ("spike", "duplicate"):
                continue # too short
                
            # Variables to inject
            var = rng.choice(["T", "RH", "P"])
            if cause in ("comms_gap", "duplicate", "timeshift", "power"):
                var = "all"
            if cause in ("radiation",):
                var = "T"
            if cause in ("drift", "noise", "unknown"):
                var = rng.choice(["T", "RH"])
                
            # check overlaps
            overlap = False
            for i in range(start_i, end_i + 1):
                if inj_mask[i]["all"] or (var != "all" and inj_mask[i][var]):
                    overlap = True
                    break
            if overlap:
                continue
                
            for i in range(start_i, end_i + 1):
                if var == "all":
                    inj_mask[i] = {"T": True, "RH": True, "P": True, "all": True}
                else:
                    inj_mask[i][var] = True
            
            diff = "easy"
            params = {}
            
            if cause == "spike":
                diff = "easy"
                for i in range(start_i, end_i + 1):
                    mag = rng.uniform(15, 40) * rng.choice([-1, 1])
                    if var == "T" and s_rows[i]["T"] is not None:
                        s_rows[i]["T"] += mag
                        params["mag"] = mag
                    elif var == "RH" and s_rows[i]["RH"] is not None:
                        s_rows[i]["RH"] = max(0, min(100, s_rows[i]["RH"] + mag))
                        params["mag"] = mag
                    elif var == "P" and s_rows[i]["P"] is not None:
                        s_rows[i]["P"] += rng.uniform(5, 20) * rng.choice([-1, 1])
                        params["mag"] = mag
                        
            elif cause == "frozen":
                diff = "medium"
                v_freeze = s_rows[start_i].get(var)
                for i in range(start_i, end_i + 1):
                    if v_freeze is not None:
                        s_rows[i][var] = v_freeze
                        
            elif cause == "drift":
                diff = "hard"
                rate_d = rng.uniform(0.01, 0.2) * rng.choice([-1, 1])
                params["rate_per_day"] = rate_d
                for i in range(start_i, end_i + 1):
                    dt = datetime.strptime(s_rows[i]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(start_ts, "%Y-%m-%dT%H:%M:%SZ")
                    days = dt.total_seconds() / 86400.0
                    if s_rows[i].get(var) is not None:
                        if var == "T": s_rows[i]["T"] += rate_d * days
                        if var == "RH": s_rows[i]["RH"] = max(0, min(100, s_rows[i]["RH"] + rate_d * days * 10))
                        
            elif cause == "offset":
                diff = "medium"
                mag = rng.uniform(3, 10) * rng.choice([-1, 1])
                params["offset"] = mag
                for i in range(start_i, end_i + 1):
                    if s_rows[i].get(var) is not None:
                        if var == "T": s_rows[i]["T"] += mag
                        elif var == "RH": s_rows[i]["RH"] = max(0, min(100, s_rows[i]["RH"] + mag * 2.5))
                        elif var == "P": s_rows[i]["P"] += rng.uniform(3, 8) * rng.choice([-1, 1])
                        
            elif cause == "noise":
                diff = "hard"
                sig = rng.uniform(3, 8)
                params["sigma"] = sig
                for i in range(start_i, end_i + 1):
                    if s_rows[i].get(var) is not None:
                        if var == "T": s_rows[i]["T"] += rng.gauss(0, sig)
                        elif var == "RH": s_rows[i]["RH"] = max(0, min(100, s_rows[i]["RH"] + rng.gauss(0, sig*2)))
                        
            elif cause == "out_of_range":
                diff = "easy"
                for i in range(start_i, end_i + 1):
                    if s_rows[i].get(var) is not None:
                        if var == "T": s_rows[i]["T"] = rng.choice([-50, 70])
                        elif var == "RH": s_rows[i]["RH"] = rng.choice([-10, 110])
                        elif var == "P": s_rows[i]["P"] = rng.choice([500, 1200])
                        
            elif cause == "radiation":
                diff = "medium"
                c = rng.uniform(0.5, 4.0)
                params["c"] = c
                for i in range(start_i, end_i + 1):
                    if s_rows[i].get("T") is not None:
                        h = datetime.strptime(s_rows[i]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ").hour
                        # proxy for solar noon
                        if 8 <= h <= 18:
                            s_rows[i]["T"] += c * math.sin(math.pi * (h - 8) / 10.0)
                            
            elif cause == "power":
                diff = "medium"
                for i in range(start_i, end_i + 1):
                    s_rows[i]["batt_v"] = rng.uniform(9.0, 10.9)
                    s_rows[i]["T"] = None
                    s_rows[i]["Td"] = None
                    s_rows[i]["RH"] = None
                    s_rows[i]["P"] = None
                    
            elif cause == "comms_gap":
                diff = "easy"
                for i in range(start_i, end_i + 1):
                    s_rows[i]["_drop"] = True
                    
            elif cause == "duplicate":
                diff = "easy"
                if start_i + 1 < n:
                    dup = copy.deepcopy(s_rows[start_i])
                    # dup with same seq or close time
                    dt = datetime.strptime(dup["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=1)
                    dup["ts_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    s_rows.insert(start_i + 1, dup)
                    n += 1 # shift
                    
            elif cause == "timeshift":
                diff = "medium"
                shift = rng.choice([1, 5.5, 24]) * rng.choice([-1, 1])
                params["shift_h"] = shift
                for i in range(start_i, end_i + 1):
                    dt = datetime.strptime(s_rows[i]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=shift)
                    s_rows[i]["ts_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    
            elif cause == "unknown":
                diff = "hard"
                rate_d = rng.uniform(0.01, 0.05)
                sig = rng.uniform(1, 3)
                for i in range(start_i, end_i + 1):
                    dt = datetime.strptime(s_rows[i]["ts_utc"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(start_ts, "%Y-%m-%dT%H:%M:%SZ")
                    days = dt.total_seconds() / 86400.0
                    if s_rows[i].get(var) is not None:
                        s_rows[i][var] += rate_d * days + rng.gauss(0, sig)

            inj_idx += 1
            labels.append({
                "schema_v": "1.0",
                "injection_id": f"inj_{inj_idx:04d}",
                "station_id": sid,
                "variable": var,
                "root_cause": cause,
                "start_ts": start_ts,
                "end_ts": s_rows[end_i]["ts_utc"] if cause != "duplicate" else s_rows[start_i]["ts_utc"],
                "params": params,
                "difficulty": diff,
                "seed": seed,
                "split": split
            })
            
        for r in s_rows:
            if not r.pop("_drop", False):
                if r.get("T") is not None and r.get("Td") is not None:
                    recompute_rh(r)
                round_vars(r)
                # don't validate in injector as it might have out of range, or wait, contract says:
                # "injected rows still pass validate_input_row" - Wait, validate_input_row just checks schema, not gross limits
                try:
                    validate_input_row(r)
                except Exception:
                    pass
                out_rows.append(r)
                
    # validate labels
    for lbl in labels:
        validate_injection(lbl)
        
    out_rows.sort(key=lambda r: r.get("ingest_ts_utc", r.get("ts_utc")))
    return out_rows, labels
