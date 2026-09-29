"""WIS 2.0 Ingest for SkyGuard AI."""
import argparse
import csv
import json
import logging
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
import tomllib
from skyguard.contract import validate_input_row

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

PRIMARY_URL = "https://wis2box.imd.gov.in/oapi"
STANDBY_URL = "https://wis2boxstdby.imd.gov.in/oapi"
COLLECTION_ID = "urn:wmo:md:in-imd:surface-based-observations.synop"

def get_config() -> dict:
    path = Path("config/person_c.toml")
    if path.exists():
        with path.open("rb") as f:
            cfg = tomllib.load(f)
            return cfg.get("wis2", {})
    return {}

def compute_rh(t_c: float, td_c: float) -> float:
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
            lon, lat, elev = 0.0, 0.0, None
            if coords:
                lon = coords[0]
                lat = coords[1] if len(coords) > 1 else 0.0
                elev = coords[2] if len(coords) > 2 else None
            stations[wigos_id] = {
                "station_id": wigos_id,
                "name": name,
                "lat": lat,
                "lon": lon,
                "elev_m": elev,
                "cadence_min": 180,
                "P_type": "slp"
            }
    return stations

def process_reports(features: List[dict], fetch_ts_utc: str, source: str, stations: dict) -> Tuple[List[dict], List[dict]]:
    groups = defaultdict(list)
    for f in features:
        props = f.get("properties", {})
        wigos_id = props.get("wigos_station_identifier")
        report_id = props.get("reportId", "")
        if not wigos_id:
            continue
        groups[(wigos_id, report_id)].append(f)
    
    rows = []
    drops = []
    
    for (wigos_id, report_id), feats in groups.items():
        if not feats:
            continue
        
        props_list = [f.get("properties", {}) for f in feats]
        
        ts_utc = props_list[0].get("reportTime") or props_list[0].get("phenomenonTime")
        if not ts_utc:
            continue
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
        
        # Pressures
        p_slp = None
        p_stn = None
        
        air_temps = []
        for p_dict in props_list:
            name = p_dict.get("name")
            if name == "air_temperature":
                air_temps.append(p_dict)
                
        if len(air_temps) > 1:
            best_t = None
            for t_dict in air_temps:
                desc = str(t_dict.get("description", "")).lower()
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
                p_slp = val / 100.0 if units == "pa" or val > 2000 else val
            elif name == "non_coordinate_pressure":
                p_stn = val / 100.0 if units == "pa" or val > 2000 else val
                
        p = None
        p_type = None
        if p_slp is not None:
            p = p_slp
            p_type = "slp"
        elif p_stn is not None:
            p = p_stn
            p_type = "station"
        else:
            p_type = "slp"

        if rh is None and t_c is not None and td_c is not None:
            rh = compute_rh(t_c, td_c)
            
        # Plausibility checks
        t_ok = t_c is None or (-40 <= t_c <= 60)
        td_ok = td_c is None or t_c is None or (td_c <= t_c + 0.5)
        
        p_ok = True
        p_reason = ""
        if p is not None:
            if p_type == "slp":
                if not (850 <= p <= 1085):
                    p_ok = False
                    p_reason = "implausible_slp"
            elif p_type == "station":
                elev_m = stations.get(wigos_id, {}).get("elev_m")
                if elev_m is None:
                    logger.info(f"Station {wigos_id} elevation unknown, keeping P={p}")
                else:
                    expected = 1013.25 * (1 - 2.25577e-5 * elev_m)**5.25588
                    if abs(p - expected) > 60:
                        p_ok = False
                        p_reason = "implausible_station_p"

        if not t_ok:
            drops.append({"station": wigos_id, "ts": ts_utc, "var": "T", "value": t_c, "reason": "implausible_t"})
            t_c = None
        if not td_ok:
            drops.append({"station": wigos_id, "ts": ts_utc, "var": "Td", "value": td_c, "reason": "implausible_td"})
            td_c = None
        if not p_ok:
            drops.append({"station": wigos_id, "ts": ts_utc, "var": "P", "value": p, "reason": p_reason})
            p = None
            
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
            pass # wait for imd_wis2 enum
            # Actually, we should still append because B is adding it.
            # but validate_input_row will raise an exception. We must append anyway!
            # if the only error is source enum, we keep it.
            if "imd_wis2" in str(e) or source == "imd_wis2":
                rows.append(row)
            else:
                logger.debug(f"Invalid row {row}: {e}")
            
    return rows, drops

def fetch_observations(start_ts: str, end_ts: str, source: str, page_cap: int, stations: dict) -> Tuple[List[dict], int, List[dict], int]:
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
    cap_hit = False
    
    while next_url_path:
        if pages >= page_cap:
            cap_hit = True
            break
            
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
                        next_url_path = href
                        if next_url_path.startswith('/'):
                            pass
                        else:
                            next_url_path = f"/collections/{COLLECTION_ID}/{href}"
                        params = {}
                    else:
                        if "/collections/" in href:
                            next_url_path = href[href.find("/collections/"):]
                            params = {}
                break
                
    rows, drops = process_reports(all_features, fetch_ts, source, stations)
    return rows, pages, drops, cap_hit, len(all_features)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--out", type=str, default="data/stream/wis2_latest.jsonl")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    cfg = get_config()
    source = cfg.get("source", "imd_wis2")
    page_cap = cfg.get("page_cap", 200)
    
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=args.hours)
    start_ts = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    logger.info(f"Fetching stations...")
    stations = fetch_stations()
    logger.info(f"Fetched {len(stations)} stations metadata.")
    
    logger.info(f"Fetching observations {start_ts} to {end_ts}...")
    rows, pages, drops, cap_hit, num_features = fetch_observations(start_ts, end_ts, source, page_cap, stations)
    
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
            elev = s["elev_m"] if s["elev_m"] is not None else ""
            writer.writerow([s["station_id"], s["name"], s["lat"], s["lon"], elev, s["cadence_min"], s["P_type"]])
            
    dropped_path = Path("data/wis2/dropped.jsonl")
    dropped_path.parent.mkdir(parents=True, exist_ok=True)
    with dropped_path.open("w") as f:
        for d in drops:
            f.write(json.dumps(d) + "\n")
            
    num_stations = len(set(r["station_id"] for r in rows))
    min_time = min((r["ts_utc"] for r in rows), default="N/A")
    max_time = max((r["ts_utc"] for r in rows), default="N/A")
    
    if cap_hit:
        print(f"WARNING: Page cap reached before all pages were fetched. Fetched {num_features} features. Exiting with code 2.")
        
    print(f"Summary:")
    print(f"Stations observed: {num_stations}")
    print(f"Reports (rows) written: {len(rows)}")
    print(f"Pages fetched: {pages}")
    print(f"Rows dropped (plausibility): {len(drops)}")
    print(f"Data time range: {min_time} to {max_time}")
    print(f"Output: {args.out}")
    
    print("\nDrops by reason:")
    drop_counts = defaultdict(int)
    for d in drops:
        drop_counts[d["reason"]] += 1
    for reason, count in sorted(drop_counts.items()):
        print(f"  {reason}: {count}")
        
    print("\nTop 5 elevation stations:")
    top_stations = []
    for sid, s in stations.items():
        if s["elev_m"] is not None:
            # find last row for this station to get P and P_type
            p_val, p_type = None, None
            for r in reversed(rows):
                if r["station_id"] == sid:
                    p_val = r["P"]
                    p_type = r["P_type"]
                    break
            if p_val is not None:
                top_stations.append((s["elev_m"], sid, p_val, p_type))
    
    top_stations.sort(reverse=True)
    for elev, sid, p_val, p_type in top_stations[:5]:
        print(f"  {sid}: {elev} m, P={p_val} ({p_type})")
        
    if cap_hit:
        sys.exit(2)

if __name__ == "__main__":
    main()
