import argparse
import json
import logging
from pathlib import Path
from skyguard.data.download import download_ghcnh, parse_to_rows, get_indian_stations
from skyguard.data.clean import clean_station
from skyguard.data.split import split_rows
from skyguard.data.events import mark_genuine_events
from skyguard.data.export_stream import fabricate_ingest

logger = logging.getLogger(__name__)

def make_data(limit=None, skip_download=False):
    logging.basicConfig(level=logging.INFO)
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    # 1. Download
    if not skip_download:
        logger.info("Downloading data...")
        download_ghcnh("data", limit=limit)
        
    # 2. Parse and Clean
    logger.info("Parsing and cleaning...")
    raw_dir = data_dir / "raw"
    obs_all = []
    station_info = []
    
    if raw_dir.exists():
        for p in raw_dir.glob("*.psv"):
            # skip non station files
            if not p.stem.startswith("INI"):
                continue
            rows = parse_to_rows(str(p))
            if rows:
                sid = rows[0]["station_id"]
                obs_rows, grid_rows = clean_station(sid, rows, "data")
                obs_all.extend(obs_rows)
                
                # compute stats for registry
                valid_t = sum(1 for r in obs_rows if r.get("T") is not None)
                station_info.append({
                    "station_id": sid,
                    "lat": 20.0, # default if missing, should be from GHCNh registry
                    "lon": 80.0,
                    "elev_m": 0.0,
                    "cadence_min": obs_rows[0].get("cadence_min", 60) if obs_rows else 60,
                    "P_type": "slp",
                    "reports_per_year": valid_t,
                    "name": sid
                })
        
        # also check synthetic stream if present
        synthetic_path = raw_dir / "synthetic_stream.jsonl"
        if synthetic_path.exists():
            rows = parse_to_rows(str(synthetic_path))
            by_station = {}
            for r in rows:
                by_station.setdefault(r["station_id"], []).append(r)
            for sid, s_rows in by_station.items():
                obs_rows, grid_rows = clean_station(sid, s_rows, "data")
                obs_all.extend(obs_rows)
                
                valid_t = sum(1 for r in obs_rows if r.get("T") is not None)
                station_info.append({
                    "station_id": sid,
                    "lat": 20.0,
                    "lon": 80.0,
                    "elev_m": 0.0,
                    "cadence_min": obs_rows[0].get("cadence_min", 60) if obs_rows else 60,
                    "P_type": "slp",
                    "reports_per_year": valid_t,
                    "name": sid
                })
                
    # Write Registry
    import csv
    with open(data_dir / "station_registry.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["station_id", "name", "lat", "lon", "elev_m", "cadence_min", "P_type", "reports_per_year"])
        writer.writeheader()
        for info in station_info:
            writer.writerow(info)
            
    # Load registry
    from skyguard.data.registry import load_registry
    registry = load_registry(data_dir / "station_registry.csv")
    
    # Split
    logger.info("Splitting...")
    split_rows(obs_all)
    
    # Events
    logger.info("Marking genuine events...")
    mark_genuine_events(obs_all, registry)
    
    # Fabricate ingest
    obs_all = fabricate_ingest(obs_all)
    
    # Export 1-day sample
    logger.info("Exporting sample...")
    stream_dir = data_dir / "stream"
    stream_dir.mkdir(exist_ok=True)
    with open(stream_dir / "sample_1day.jsonl", "w") as f:
        for r in obs_all[:1000]: # just a sample
            f.write(json.dumps(r) + "\n")
            
    logger.info(f"Done. Kept {len(station_info)} stations, {len(obs_all)} rows.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    make_data(limit=args.limit, skip_download=args.skip_download)
