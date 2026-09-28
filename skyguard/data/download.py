import argparse
import csv
import json
import logging
import random
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from skyguard.contract import validate_input_row, ContractError

logger = logging.getLogger(__name__)

def get_config():
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

def download_file(url: str, dest: Path, retries: int = 3, timeout: int = 120) -> bool:
    if dest.exists():
        return True
    
    part_dest = dest.with_suffix(".part")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as response, open(part_dest, 'wb') as out_file:
                out_file.write(response.read())
            part_dest.rename(dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            time.sleep(2 ** attempt)
        except Exception as e:
            time.sleep(2 ** attempt)
    return False

def get_indian_stations(limit: int = None, stations: List[str] = None) -> List[str]:
    if stations:
        return stations
        
    url = "https://www.ncei.noaa.gov/data/global-hourly-climatology-network/doc/ghcnh-station-list.csv"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    indian_stations = []
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            lines = response.read().decode('utf-8').splitlines()
            reader = csv.DictReader(lines)
            for row in reader:
                sid = row.get("Station_ID", row.get("STATION", ""))
                if sid.startswith("IN"):
                    indian_stations.append(sid)
    except Exception as e:
        logger.warning(f"Failed to download station list: {e}")
        # fallback to a default list or synthetic logic
        indian_stations = [f"INI{i:04d}" for i in range(40)]
        
    if limit:
        indian_stations = indian_stations[:limit]
    return indian_stations

def download_ghcnh(dest_dir: str, years: Tuple[int, ...] = (2023, 2024), limit: int = None, stations: List[str] = None) -> None:
    dest_path = Path(dest_dir) / "raw"
    dest_path.mkdir(parents=True, exist_ok=True)
    
    config = get_config().get("download", {})
    workers = config.get("workers", 8)
    retries = config.get("retries", 3)
    timeout_s = config.get("timeout_s", 120)
    config_years = config.get("years", list(years))
    
    indian_stations = get_indian_stations(limit, stations)
    if not indian_stations:
        return
        
    tasks = []
    for sid in indian_stations:
        for year in config_years:
            url = f"https://www.ncei.noaa.gov/data/global-hourly-climatology-network/access/by-year/{year}/psv/GHCNh_{sid}_{year}.psv"
            dest_file = dest_path / f"{sid}_{year}.psv"
            tasks.append((url, dest_file))
            
    success_count = 0
    not_found = 0
    failed = 0
    
    log_data = []
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_task = {executor.submit(download_file, url, dest, retries, timeout_s): (url, dest) for url, dest in tasks}
        
        count = 0
        for future in as_completed(future_to_task):
            url, dest = future_to_task[future]
            try:
                success = future.result()
                if success:
                    success_count += 1
                    log_data.append({"url": url, "status": "success", "file": str(dest)})
                else:
                    not_found += 1
                    log_data.append({"url": url, "status": "404"})
            except Exception as e:
                failed += 1
                log_data.append({"url": url, "status": "error", "error": str(e)})
                
            count += 1
            if count % 50 == 0:
                logger.info(f"Downloaded {count}/{len(tasks)} files...")
                
    if success_count == 0:
        logger.warning("No files downloaded. Generating synthetic data...")
        from skyguard.ingest.replay import generate_synthetic_stream
        # We need to simulate the downloaded files
        # However, the pipeline expects PSV files in raw.
        # But if the URL is unreachable we fallback. 
        # Actually, if we couldn't download anything, generating synthetic stream happens here or in clean?
        # The prompt says: "If the NCEI URL is unreachable... fall back to generating synthetic data using... generate_synthetic_stream with >= 40 stations and >= 500 rows per station. Log a warning."
        stream = generate_synthetic_stream(num_stations=40, num_clusters=4, rows_per_station=500)
        import json
        with open(dest_path / "synthetic_stream.jsonl", "w") as f:
            for row in stream:
                f.write(json.dumps(row) + "\n")
        
    with open(Path(dest_dir) / "download_log.json", "w") as f:
        json.dump(log_data, f, indent=2)

def parse_to_rows(raw_path: str) -> List[dict]:
    path = Path(raw_path)
    if path.name == "synthetic_stream.jsonl":
        rows = []
        with open(path, "r") as f:
            for line in f:
                rows.append(json.loads(line))
        return rows

    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            for row in reader:
                # Lowercase all column names for consistent access
                row = {k.lower() if k else k: v for k, v in row.items()}
                
                try:
                    station_id = row.get("station", "")
                    # Dates come in as YYYYMMDD and time as HHMM?
                    # "DATE" is usually YYYY-MM-DDTHH:MM:SS
                    date_str = row.get("date", "").replace(" ", "T")
                    if not date_str.endswith("Z"):
                        date_str += "Z"
                        
                    t_val = row.get("temperature", "")
                    td_val = row.get("dew_point_temperature", "")
                    rh_val = row.get("relative_humidity", "")
                    p_val = row.get("sea_level_pressure", "")
                    alt_val = row.get("altimeter", "")
                    
                    def to_float(v):
                        try:
                            f = float(v)
                            return f if f != -9999.0 else None
                        except (ValueError, TypeError):
                            return None
                            
                    t = to_float(t_val)
                    if t is not None:
                        t = t / 10.0 # typically tenths of C
                        
                    td = to_float(td_val)
                    if td is not None:
                        td = td / 10.0
                        
                    rh = to_float(rh_val)
                    if rh is not None:
                        rh = rh / 10.0
                        
                    p = to_float(p_val)
                    if p is not None:
                        p = p / 10.0
                    else:
                        p = to_float(alt_val)
                        if p is not None:
                            p = p / 10.0
                            
                    report_type = row.get("report_type", "")
                    if "FM-12" in report_type or "SYNOP" in report_type:
                        source = "ghcnh_synop"
                        cadence = 180
                    elif "FM-15" in report_type or "METAR" in report_type:
                        source = "ghcnh_metar"
                        cadence = 60
                    elif "FM-16" in report_type or "SPECI" in report_type:
                        source = "ghcnh_speci"
                        cadence = 60
                    else:
                        source = "ghcnh_synop"
                        cadence = 180
                        
                    qc = {}
                    for var, col in [("T", "temperature"), ("Td", "dew_point_temperature"), ("RH", "relative_humidity"), ("P", "sea_level_pressure")]:
                        q = row.get(f"{col}_quality_code", "")
                        if q:
                            qc[var] = q
                            
                    out_row = {
                        "schema_v": "1.0",
                        "station_id": station_id,
                        "ts_utc": date_str,
                        "T": t,
                        "Td": td,
                        "RH": rh,
                        "P": p,
                        "P_type": "slp",
                        "cadence_min": cadence,
                        "source": source,
                        "qc": qc
                    }
                    
                    validate_input_row(out_row)
                    rows.append(out_row)
                except ContractError:
                    continue
                except Exception as e:
                    continue
    except Exception as e:
        logger.error(f"Failed to parse {raw_path}: {e}")
        
    return rows

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=[2023, 2024])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stations", nargs="+", type=str, default=None)
    parser.add_argument("--dest", type=str, default="data")
    args = parser.parse_args()
    download_ghcnh(args.dest, years=tuple(args.years), limit=args.limit, stations=args.stations)
