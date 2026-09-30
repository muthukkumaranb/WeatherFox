"""scripts/make_data.py — master pipeline: download → clean → registry → split → events → export.

Usage:
    python scripts/make_data.py                 # full run
    python scripts/make_data.py --limit 10      # only first 10 Indian stations
    python scripts/make_data.py --skip-download # rebuild from existing raw/ files
"""
import argparse
import csv
import json
import logging
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA   = Path("data")
SPLITS = Path("splits")


def make_data(limit=None, skip_download=False):
    t0 = time.perf_counter()
    DATA.mkdir(exist_ok=True)

    # ── 1. Download ──────────────────────────────────────────────────────────
    from skyguard.data.download import download_ghcnh, parse_to_rows, get_indian_stations

    if skip_download:
        station_info = get_indian_stations(limit=limit)
    else:
        logger.info("=== DOWNLOAD ===")
        station_info = download_ghcnh("data", limit=limit)

    # Build a station-id → {lat,lon,elev,name} lookup from the station list
    info_by_sid: dict[str, dict] = {}
    for rec in station_info:
        info_by_sid[rec["station_id"]] = rec

    # ── 2. Parse + Clean ─────────────────────────────────────────────────────
    logger.info("=== PARSE + CLEAN ===")
    from skyguard.data.clean import clean_station

    raw_dir = DATA / "raw"
    all_obs: list[dict] = []
    station_stats: dict[str, dict] = {}  # sid → {rows, years, ...}

    psv_files = sorted(raw_dir.glob("IN*_*.psv")) if raw_dir.exists() else []
    # Filter by info_by_sid to respect --limit
    psv_files = [p for p in psv_files if p.name.split("_")[0] in info_by_sid]
    
    synth_file = raw_dir / "synthetic_stream.jsonl" if raw_dir.exists() else None

    if psv_files:
        for i, p in enumerate(psv_files):
            rows = parse_to_rows(str(p))
            if not rows:
                continue
            sid = rows[0]["station_id"]

            # inject lat/lon from station list into rows (for events etc.)
            meta = info_by_sid.get(sid, {})
            for r in rows:
                r.setdefault("lat", meta.get("lat", 20.0))
                r.setdefault("lon", meta.get("lon", 80.0))

            obs_rows, _ = clean_station(sid, rows, "data")
            all_obs.extend(obs_rows)

            # stats
            ss = station_stats.setdefault(sid, {
                "lat": meta.get("lat", 20.0),
                "lon": meta.get("lon", 80.0),
                "elev_m": meta.get("elev_m", 0.0),
                "name": meta.get("name", sid),
                "rows": 0, "years": set(), "cadence_min": 60, "P_type": "slp",
            })
            ss["rows"] += len(obs_rows)
            for r in obs_rows:
                try:
                    yr = datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ").year
                    ss["years"].add(yr)
                except Exception:
                    pass
            if obs_rows:
                ss["cadence_min"] = obs_rows[0].get("cadence_min", 60)

            if (i + 1) % 20 == 0:
                logger.info(f"  parsed {i+1}/{len(psv_files)} PSV files …")

    elif synth_file and synth_file.exists():
        logger.info("Using synthetic stream (no PSVs found)")
        rows = parse_to_rows(str(synth_file))
        by_sid: dict[str, list] = {}
        for r in rows:
            by_sid.setdefault(r["station_id"], []).append(r)
        for sid, s_rows in by_sid.items():
            obs_rows, _ = clean_station(sid, s_rows, "data")
            all_obs.extend(obs_rows)
            station_stats[sid] = {
                "lat": 20.0, "lon": 80.0, "elev_m": 0.0, "name": sid,
                "rows": len(obs_rows), "years": {2024}, "cadence_min": 60, "P_type": "slp",
            }

    # ── 3. Registry ──────────────────────────────────────────────────────────
    logger.info("=== REGISTRY ===")
    reg_path = DATA / "station_registry.csv"
    with open(reg_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "station_id", "name", "lat", "lon", "elev_m",
            "cadence_min", "P_type", "reports_per_year",
        ])
        w.writeheader()
        for sid, ss in sorted(station_stats.items()):
            nyears = max(len(ss["years"]), 1)
            w.writerow({
                "station_id": sid,
                "name": ss["name"],
                "lat": ss["lat"],
                "lon": ss["lon"],
                "elev_m": ss["elev_m"],
                "cadence_min": ss["cadence_min"],
                "P_type": ss["P_type"],
                "reports_per_year": ss["rows"] // nyears,
            })

    from skyguard.data.registry import load_registry
    registry = load_registry(reg_path)

    # ── 4. Split ─────────────────────────────────────────────────────────────
    logger.info("=== SPLIT ===")
    from skyguard.data.split import split_rows
    partitioned = split_rows(all_obs)
    for sp, rows in partitioned.items():
        logger.info(f"  {sp}: {len(rows)} rows, {len({r['station_id'] for r in rows})} stations")

    # ── 5. Events ────────────────────────────────────────────────────────────
    logger.info("=== EVENTS ===")
    from skyguard.data.events import mark_genuine_events
    mark_genuine_events(all_obs, registry)

    # ── 6. Fabricate ingest + export ─────────────────────────────────────────
    logger.info("=== EXPORT ===")
    from skyguard.data.export_stream import fabricate_ingest
    all_obs = fabricate_ingest(all_obs)

    stream_dir = DATA / "stream"
    stream_dir.mkdir(exist_ok=True)
    sample_rows = [r for r in all_obs if r.get("ts_utc", "") < all_obs[0]["ts_utc"][:11] + "24:00:00Z"][:2000]
    if len(sample_rows) < 100:
        sample_rows = all_obs[:2000]
    with open(stream_dir / "sample_1day.jsonl", "w", encoding="utf-8") as fh:
        for r in sample_rows:
            fh.write(json.dumps(r) + "\n")

    elapsed = time.perf_counter() - t0

    # ── Summary ──────────────────────────────────────────────────────────────
    ts_list = sorted(r["ts_utc"] for r in all_obs if r.get("ts_utc"))
    date_min = ts_list[0][:10] if ts_list else "?"
    date_max = ts_list[-1][:10] if ts_list else "?"

    print("\n" + "=" * 60)
    print("  make_data.py — SUMMARY")
    print("=" * 60)
    print(f"  Stations kept : {len(station_stats)}")
    print(f"  Total rows    : {len(all_obs):,}")
    print(f"  Date range    : {date_min}  ->  {date_max}")
    print(f"  Splits        : train {len(partitioned['train']):,} | "
          f"val_cal {len(partitioned['val_cal']):,} | val_eval {len(partitioned['val_eval']):,} | test {len(partitioned['test']):,}")
    print(f"  Registry      : {reg_path}")
    print(f"  Elapsed       : {elapsed:.1f} s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    make_data(limit=args.limit, skip_download=args.skip_download)
