"""WIS 2.0 Ingest for SkyGuard AI."""
import argparse
import csv
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import urllib3
import tomllib
from skyguard.contract import validate_input_row

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

PRIMARY_URL = "https://wis2box.imd.gov.in/oapi"
STANDBY_URL = "https://wis2boxstdby.imd.gov.in/oapi"
COLLECTION_ID = "urn:wmo:md:in-imd:surface-based-observations.synop"

def get_config_source() -> str:
    path = Path("config/person_c.toml")
    if path.exists():
        with path.open("rb") as f:
            cfg = tomllib.load(f)
            return cfg.get("wis2", {}).get("source", "ghcnh_synop")
    return "ghcnh_synop"

def compute_rh(t_c: float, td_c: float) -> float:
    # Magnus formula
    a = 17.625
    b = 243.04
    e_td = math.exp((a * td_c) / (b + td_c))
    e_t = math.exp((a * t_c) / (b + t_c))
    rh = 100.0 * (e_td / e_t)
    return max(0.0, min(100.0, rh))

def fetch_json(url: str, params: Dict[str, Any], timeout: int = 20) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": "SkyGuard-WIS2-Ingest/1.0"}
    time.sleep(1)  # polite 1 req/s
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None

def fetch_with_fallback(path: str, params: Dict[str, Any], timeout: int = 20) -> Optional[Dict[str, Any]]:
    for base in (PRIMARY_URL, STANDBY_URL):
        url = f"{base}{path}"
        res = fetch_json(url, params, timeout)
        if res is not None:
            return res
    return None

def fetch_stations() -> Dict[str, dict]:
    stations = {}
    path = "/collections/stations/items"
    params = {"limit": 500, "f": "json"}
    data = fetch_with_fallback(path, params)
    if data and "features" in data:
        for f in data["features"]:
            props = f.get("properties", {})
            wigos_id = props.get("wigos_station_identifier")
            if not wigos_id:
                continue
            name = props.get("name", "")
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [])
            lon, lat, elev = 0.0, 0.0, 0.0
            if coords:
                lon = coords[0]
                lat = coords[1] if len(coords) > 1 else 0.0
                elev = coords[2] if len(coords) > 2 else 0.0
            stations[wigos_id] = {
                "station_id": wigos_id,
                "name": name,
                "lat": lat,
                "lon": lon,
                "elev_m": elev,
                "cadence_min": 180,
                "P_type": "slp" # default, updated by obs
            }
    return stations

def process_reports(features: List[dict], fetch_ts_utc: str, source: str) -> tuple[List[dict], int]:
    # Group by (wigos_station_identifier, reportId)
    groups = defaultdict(list)
    for f in features:
        props = f.get("properties", {})
        wigos_id = props.get("wigos_station_identifier")
        report_id = props.get("reportId", "")
        if not wigos_id:
            continue
        groups[(wigos_id, report_id)].append(f)
    
    rows = []
    dropped_rows = 0
    
    for (wigos_id, report_id), feats in groups.items():
        if not feats:
            continue
        
        props_list = [f.get("properties", {}) for f in feats]
        
        # Get common times
        ts_utc = props_list[0].get("reportTime") or props_list[0].get("phenomenonTime")
        if not ts_utc:
            continue
        # Standardize ISO Z
        if not ts_utc.endswith("Z"):
            ts_utc = ts_utc.replace("+00:00", "Z")
            if not ts_utc.endswith("Z"):
                ts_utc += "Z"
                
        ingest_ts_utc = props_list[0].get("resultTime") or fetch_ts_utc
        if not ingest_ts_utc.endswith("Z"):
            ingest_ts_utc = ingest_ts_utc.replace("+00:00", "Z")
            if not ingest_ts_utc.endswith("Z"):
                ingest_ts_utc += "Z"
        
        t_c = None
        td_c = None
        rh = None
        p = None
        p_type = None
        
        # Pick surface temperature (1.5 - 2m height)
        # We find all air_temperature features, and if multiple, try to find one with height 1.5-2m
        air_temps = []
        for p_dict in props_list:
            name = p_dict.get("name")
            if name == "air_temperature":
                air_temps.append(p_dict)
                
        if len(air_temps) > 1:
            best_t = None
            for t_dict in air_temps:
                desc = str(t_dict.get("description", "")).lower()
                # Check if height is around 1.5-2m or if it's the standard surface temp (no description)
                # The diagnosis might have shown no height/description, so we just pick the first if we can't tell
                best_t = t_dict
                if "1.5" in desc or "2" in desc or "surface" in desc:
                    break
            if best_t:
                air_temps = [best_t]
                
        if air_temps:
            t_dict = air_temps[0]
            val = t_dict.get("value")
            units = t_dict.get("units", "").lower()
            if val is not None:
                if units in ("k", "kelvin") or val > 100:
                    t_c = val - 273.15
                else:
                    t_c = val

        for p_dict in props_list:
            name = p_dict.get("name")
            val = p_dict.get("value")
            units = str(p_dict.get("units", "")).lower()
            if val is None:
                continue
            
            if name == "dewpoint_temperature":
                if units in ("k", "kelvin") or val > 100:
                    td_c = val - 273.15
                else:
                    td_c = val
            elif name == "relative_humidity":
                rh = val
            elif name == "pressure_reduced_to_mean_sea_level":
                p = val / 100.0 if units == "pa" or val > 2000 else val
                p_type = "slp"
            elif name == "non_coordinate_pressure":
                if p_type != "slp":
                    p = val / 100.0 if units == "pa" or val > 2000 else val
                    p_type = "station"
        
        if p_type is None:
            p_type = "slp"

        if rh is None and t_c is not None and td_c is not None:
            rh = compute_rh(t_c, td_c)
            
        # Plausibility checks
        t_ok = t_c is None or (-40 <= t_c <= 60)
        td_ok = td_c is None or t_c is None or (td_c <= t_c + 0.5)
        p_ok = p is None or (850 <= p <= 1085)
        
        if not t_ok:
            logger.warning(f"Dropping implausible T={t_c} for {wigos_id}")
            t_c = None
            dropped_rows += 1
        if not td_ok:
            logger.warning(f"Dropping implausible Td={td_c} (T={t_c}) for {wigos_id}")
            td_c = None
            dropped_rows += 1
        if not p_ok:
            logger.warning(f"Dropping implausible P={p} for {wigos_id}")
            p = None
            dropped_rows += 1
            
        row = {
            "schema_v": "1.0",
            "station_id": wigos_id,
            "ts_utc": ts_utc,
            "ingest_ts_utc": ingest_ts_utc,
            "seq": 0,
            "T": round(t_c, 2) if t_c is not None else None,
            "Td": round(td_c, 2) if td_c is not None else None,
            "RH": round(rh, 2) if rh is not None else None,
            "P": round(p, 2) if p is not None else None,
            "P_type": p_type,
            "cadence_min": 180,
            "source": source
        }
        
        try:
            validate_input_row(row)
            rows.append(row)
        except Exception as e:
            logger.debug(f"Invalid row {row}: {e}")
            
    return rows, dropped_rows

def fetch_observations(start_ts: str, end_ts: str, source: str) -> tuple[List[dict], int, int]:
    path = f"/collections/{COLLECTION_ID}/items"
    params = {
        "f": "json",
        "limit": 1000,
        "datetime": f"{start_ts}/{end_ts}"
    }
    fetch_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    all_features = []
    next_url_path = path
    pages = 0
    
    while next_url_path and pages < 60:
        pages += 1
        data = fetch_with_fallback(next_url_path, params)
        if not data:
            break
            
        features = data.get("features", [])
        all_features.extend(features)
        
        links = data.get("links", [])
        next_url_path = None
        for link in links:
            if link.get("rel") == "next":
                href = link.get("href", "")
                if href:
                    if "http" not in href:
                        # Keep original query params when the next href is relative, or if it already has params?
                        # Actually if it's a relative URL, WIS2 might give something like `?offset=1000&limit=1000`
                        # We just use that as the path + query. But fetch_with_fallback uses base + path.
                        next_url_path = href
                        if next_url_path.startswith('/'):
                            # Absolute path but relative to domain
                            pass
                        else:
                            # Relative path
                            next_url_path = f"/collections/{COLLECTION_ID}/{href}"
                        params = {} # params are in the URL
                    else:
                        if "/collections/" in href:
                            next_url_path = href[href.find("/collections/"):]
                            params = {}
                break
                
    rows, dropped = process_reports(all_features, fetch_ts, source)
    return rows, pages, dropped

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--out", type=str, default="data/stream/wis2_latest.jsonl")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    source = get_config_source()
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.hours)
    start_ts = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    logger.info(f"Fetching stations...")
    stations = fetch_stations()
    logger.info(f"Fetched {len(stations)} stations metadata.")
    
    logger.info(f"Fetching observations {start_ts} to {end_ts}...")
    rows, pages, dropped = fetch_observations(start_ts, end_ts, source)
    
    if not rows:
        logger.info("No rows fetched.")
        return
        
    # infer cadence and update station registry p_type
    station_times = defaultdict(list)
    for r in rows:
        station_times[r["station_id"]].append(r["ts_utc"])
        
    for sid, t_list in station_times.items():
        if len(t_list) > 1:
            t_list.sort()
            diffs = []
            for i in range(1, len(t_list)):
                dt1 = datetime.fromisoformat(t_list[i-1].replace("Z", "+00:00"))
                dt2 = datetime.fromisoformat(t_list[i].replace("Z", "+00:00"))
                diffs.append((dt2 - dt1).total_seconds() / 60)
            avg_diff = sum(diffs)/len(diffs)
            if avg_diff < 100: # if mostly hourly
                cadence = 60
            else:
                cadence = 180
        else:
            cadence = 180
            
        if sid in stations:
            stations[sid]["cadence_min"] = cadence
            # find P_type from last row
            for r in reversed(rows):
                if r["station_id"] == sid:
                    stations[sid]["P_type"] = r["P_type"]
                    break
        
        # update row cadence
        for r in rows:
            if r["station_id"] == sid:
                r["cadence_min"] = cadence
                
    # sequence assignment
    counts = defaultdict(int)
    for r in sorted(rows, key=lambda x: x["ts_utc"]):
        r["seq"] = counts[r["station_id"]]
        counts[r["station_id"]] += 1
        
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
            
    reg_path = Path("data/wis2/stations.csv")
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    with reg_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "name", "lat", "lon", "elev_m", "cadence_min", "P_type"])
        for sid, s in stations.items():
            writer.writerow([s["station_id"], s["name"], s["lat"], s["lon"], s["elev_m"], s["cadence_min"], s["P_type"]])
            
    num_stations = len(set(r["station_id"] for r in rows))
    min_time = min((r["ts_utc"] for r in rows), default="N/A")
    max_time = max((r["ts_utc"] for r in rows), default="N/A")
    
    print(f"Summary:")
    print(f"Stations observed: {num_stations}")
    print(f"Reports (rows) written: {len(rows)}")
    print(f"Pages fetched: {pages}")
    print(f"Rows dropped (plausibility): {dropped}")
    print(f"Data time range: {min_time} to {max_time}")
    print(f"Output: {args.out}")

if __name__ == "__main__":
    main()
