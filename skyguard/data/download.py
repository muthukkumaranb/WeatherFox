"""GHCNh downloader — Indian stations only.

Station list: fixed-width text from
  https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt
Per-station-year PSV from
  https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{YEAR}/psv/GHCNh_{ID}_{YEAR}.psv

Temperature, dew point, pressures are ALREADY in °C / hPa — do NOT divide by 10.
"""
import argparse
import csv
import json
import logging
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from skyguard.contract import validate_input_row, ContractError

logger = logging.getLogger(__name__)

STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network"
    "/hourly/doc/ghcnh-station-list.txt"
)
PSV_BASE = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network"
    "/hourly/access/by-year"
)


def get_config():
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


# ── helpers ──────────────────────────────────────────────────────────────────

def download_file(url: str, dest: Path, retries: int = 3, timeout: int = 120) -> bool:
    """Download *url* to *dest*, resumable (skip if exists), with retries."""
    if dest.exists() and dest.stat().st_size > 0:
        return True

    part_dest = dest.with_suffix(".part")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, \
                    open(part_dest, "wb") as out:
                out.write(resp.read())
            part_dest.rename(dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False  # missing station-year, normal
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return False


def _parse_station_line(line: str) -> dict | None:
    """Parse one fixed-width line from the GHCNh station list.

    Columns (1-based): id 1–11, lat 13–20, lon 22–30, elev 32–37,
    state 39–40, name 42–71, gsn 73–75, hcn/crn 77–79, wmo 81–end.
    """
    if len(line) < 40:
        return None
    sid  = line[0:11].strip()
    try:
        lat  = float(line[12:20].strip())
        lon  = float(line[21:30].strip())
    except ValueError:
        return None
    try:
        elev = float(line[31:37].strip())
    except ValueError:
        elev = 0.0
    name = line[41:71].strip()
    return {"station_id": sid, "lat": lat, "lon": lon, "elev_m": elev, "name": name}


def get_indian_stations(limit: int = None, stations: List[str] = None) -> list[dict]:
    """Return list of dicts with station_id/lat/lon/elev_m/name for Indian stations."""
    if stations:
        return [{"station_id": s, "lat": 20, "lon": 80, "elev_m": 0, "name": s}
                for s in stations]

    cache_path = Path("data") / "raw" / "ghcnh_station_list.txt"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if not cache_path.exists():
        logger.info("Downloading GHCNh station list …")
        download_file(STATION_LIST_URL, cache_path)

    indian: list[dict] = []
    try:
        with open(cache_path, encoding="utf-8") as fh:
            for line in fh:
                rec = _parse_station_line(line)
                if rec is None:
                    continue
                sid = rec["station_id"]
                lat, lon = rec["lat"], rec["lon"]
                # India filter: id starts with IN, lat 6–37.5, lon 68–97.5
                if sid.startswith("IN") and 6 <= lat <= 37.5 and 68 <= lon <= 97.5:
                    indian.append(rec)
    except Exception as e:
        logger.error(f"Cannot read station list: {e}")

    if limit:
        indian = indian[:limit]

    logger.info(f"Indian stations found: {len(indian)}")
    return indian


# ── main download ────────────────────────────────────────────────────────────

def download_ghcnh(
    dest_dir: str,
    years: Tuple[int, ...] = (2023, 2024),
    limit: int = None,
    stations: List[str] = None,
) -> list[dict]:
    """Download station-year PSV files; return the station-info list."""
    dest_path = Path(dest_dir) / "raw"
    dest_path.mkdir(parents=True, exist_ok=True)

    config = get_config().get("download", {})
    workers  = config.get("workers", 8)
    retries  = config.get("retries", 3)
    timeout  = config.get("timeout_s", 120)
    cfg_yrs  = config.get("years", list(years))

    station_info = get_indian_stations(limit, stations)
    if not station_info:
        logger.warning("No Indian stations found.")
        return []

    tasks = []
    for rec in station_info:
        sid = rec["station_id"]
        for year in cfg_yrs:
            url  = f"{PSV_BASE}/{year}/psv/GHCNh_{sid}_{year}.psv"
            dest = dest_path / f"{sid}_{year}.psv"
            tasks.append((url, dest))

    success_count = 0
    not_found     = 0
    log_data: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(download_file, u, d, retries, timeout): (u, d)
                for u, d in tasks}
        done = 0
        for fut in as_completed(futs):
            url, dest = futs[fut]
            try:
                ok = fut.result()
                if ok:
                    success_count += 1
                    log_data.append({"url": url, "status": "success", "file": str(dest)})
                else:
                    not_found += 1
                    log_data.append({"url": url, "status": "404"})
            except Exception as e:
                log_data.append({"url": url, "status": "error", "error": str(e)})
            done += 1
            if done % 50 == 0:
                logger.info(f"  … {done}/{len(tasks)} files")

    logger.info(f"Downloaded {success_count} files, {not_found} missing (404)")

    if success_count == 0:
        logger.warning("No PSV files downloaded — falling back to synthetic stream.")
        from skyguard.ingest.replay import generate_synthetic_stream
        stream = generate_synthetic_stream(num_stations=40, num_clusters=4,
                                           rows_per_station=500)
        with open(dest_path / "synthetic_stream.jsonl", "w", encoding="utf-8") as fh:
            for row in stream:
                fh.write(json.dumps(row) + "\n")

    with open(Path(dest_dir) / "download_log.json", "w", encoding="utf-8") as fh:
        json.dump(log_data, fh, indent=2)

    return station_info


# ── PSV parser ───────────────────────────────────────────────────────────────

def _safe_float(v: str) -> float | None:
    try:
        f = float(v)
        return None if f == -9999.0 else f
    except (ValueError, TypeError):
        return None


def parse_to_rows(raw_path: str) -> List[dict]:
    """Parse a single PSV (or synthetic JSONL) file → list of contract rows."""
    path = Path(raw_path)

    # synthetic fallback
    if path.suffix == ".jsonl":
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rows.append(json.loads(line))
        return rows

    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="|")
            for rec in reader:
                # lowercase keys
                rec = {(k.lower() if k else k): v for k, v in rec.items()}
                try:
                    station_id = rec.get("station", "").strip()
                    date_str   = rec.get("date", "").strip()
                    if not date_str.endswith("Z"):
                        date_str += "Z"

                    # Values are already in °C / hPa — NO division by 10
                    t  = _safe_float(rec.get("temperature", ""))
                    td = _safe_float(rec.get("dew_point_temperature", ""))
                    rh = _safe_float(rec.get("relative_humidity", ""))

                    # P: prefer SLP, else altimeter
                    p = _safe_float(rec.get("sea_level_pressure", ""))
                    if p is None:
                        p = _safe_float(rec.get("altimeter", ""))

                    # report type / source / cadence
                    rpt = rec.get("temperature_report_type",
                                  rec.get("sea_level_pressure_report_type", ""))
                    if "FM12" in rpt or "FM-12" in rpt:
                        source  = "ghcnh_synop"
                        cadence = 180
                    elif "FM15" in rpt or "FM-15" in rpt:
                        source  = "ghcnh_metar"
                        cadence = 60
                    elif "FM16" in rpt or "FM-16" in rpt:
                        source  = "ghcnh_speci"
                        cadence = 60
                    else:
                        source  = "ghcnh_synop"
                        cadence = 180

                    qc: dict[str, str] = {}
                    for var, col in [("T", "temperature"), ("Td", "dew_point_temperature"),
                                     ("RH", "relative_humidity"), ("P", "sea_level_pressure")]:
                        q = rec.get(f"{col}_quality_code", "").strip()
                        if q:
                            qc[var] = q

                    lat = _safe_float(rec.get("latitude", ""))
                    lon = _safe_float(rec.get("longitude", ""))

                    out = {
                        "schema_v":    "1.0",
                        "station_id":  station_id,
                        "ts_utc":      date_str,
                        "T":           t,
                        "Td":          td,
                        "RH":          rh,
                        "P":           p,
                        "P_type":      "slp",
                        "cadence_min": cadence,
                        "source":      source,
                        "qc":          qc,
                    }
                    validate_input_row(out)
                    rows.append(out)
                except ContractError:
                    continue
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Failed to parse {raw_path}: {e}")
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=[2023, 2024])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stations", nargs="+", type=str, default=None)
    parser.add_argument("--dest", type=str, default="data")
    args = parser.parse_args()
    download_ghcnh(args.dest, years=tuple(args.years), limit=args.limit,
                   stations=args.stations)
