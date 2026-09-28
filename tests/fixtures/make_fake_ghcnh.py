import csv
import math
import random
from pathlib import Path
from datetime import datetime, timedelta

def create_fake_ghcnh(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    
    stations = []
    clusters = [
        {"name": "Delhi", "lat": 28.6, "lon": 77.2, "count": 4},
        {"name": "Kolkata", "lat": 22.5, "lon": 88.3, "count": 4},
        {"name": "Chennai", "lat": 13.0, "lon": 80.2, "count": 4}
    ]
    
    sid_idx = 1
    for cl in clusters:
        for i in range(cl["count"]):
            sid = f"INI{sid_idx:04d}"
            stations.append({
                "STATION_ID": sid,
                "LAT": cl["lat"] + random.uniform(-0.1, 0.1),
                "LON": cl["lon"] + random.uniform(-0.1, 0.1),
                "ELEV": random.randint(0, 200)
            })
            sid_idx += 1
            
    # write station list
    # Not strictly needed if we mock get_indian_stations, but let's write it
    
    # write PSV files
    start_dt = datetime(2023, 1, 1)
    
    for st in stations:
        sid = st["STATION_ID"]
        psv_path = raw_dir / f"{sid}_2023.psv"
        with open(psv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, delimiter="|", fieldnames=[
                "STATION", "DATE", "LATITUDE", "LONGITUDE", "ELEVATION",
                "TEMPERATURE", "DEW_POINT_TEMPERATURE", "RELATIVE_HUMIDITY",
                "STATION_LEVEL_PRESSURE", "SEA_LEVEL_PRESSURE", "ALTIMETER",
                "TEMPERATURE_QUALITY_CODE", "DEW_POINT_TEMPERATURE_QUALITY_CODE",
                "RELATIVE_HUMIDITY_QUALITY_CODE", "SEA_LEVEL_PRESSURE_QUALITY_CODE",
                "REPORT_TYPE"
            ])
            writer.writeheader()
            
            curr = start_dt
            while curr < start_dt + timedelta(days=2):
                # diurnal
                hour = curr.hour
                t = 25.0 + 10.0 * math.sin(math.pi * (hour - 6) / 12)
                td = t - 5.0
                rh = 50.0
                p = 1010.0
                
                # SYNOP every 3h
                if curr.hour % 3 == 0 and curr.minute == 0:
                    writer.writerow({
                        "STATION": sid,
                        "DATE": curr.strftime("%Y-%m-%dT%H:%M:%S"),
                        "TEMPERATURE": str(int(t * 10)),
                        "DEW_POINT_TEMPERATURE": str(int(td * 10)),
                        "RELATIVE_HUMIDITY": str(int(rh * 10)),
                        "SEA_LEVEL_PRESSURE": str(int(p * 10)),
                        "STATION_LEVEL_PRESSURE": "-9999",
                        "ALTIMETER": "-9999",
                        "TEMPERATURE_QUALITY_CODE": "1",
                        "DEW_POINT_TEMPERATURE_QUALITY_CODE": "1",
                        "RELATIVE_HUMIDITY_QUALITY_CODE": "1",
                        "SEA_LEVEL_PRESSURE_QUALITY_CODE": "1",
                        "REPORT_TYPE": "FM-12 SYNOP"
                    })
                    
                # METAR every 30min
                if curr.minute in (0, 30):
                    # add bad qc sometimes
                    qc = "1"
                    if random.random() < 0.05:
                        qc = "2" # suspect
                        
                    writer.writerow({
                        "STATION": sid,
                        "DATE": curr.strftime("%Y-%m-%dT%H:%M:%S"),
                        "TEMPERATURE": str(int(math.floor(t)) * 10),
                        "DEW_POINT_TEMPERATURE": str(int(math.floor(td)) * 10),
                        "RELATIVE_HUMIDITY": str(int(rh * 10)),
                        "SEA_LEVEL_PRESSURE": "-9999",
                        "STATION_LEVEL_PRESSURE": "-9999",
                        "ALTIMETER": str(int(p * 10)),
                        "TEMPERATURE_QUALITY_CODE": qc,
                        "DEW_POINT_TEMPERATURE_QUALITY_CODE": qc,
                        "RELATIVE_HUMIDITY_QUALITY_CODE": qc,
                        "SEA_LEVEL_PRESSURE_QUALITY_CODE": qc,
                        "REPORT_TYPE": "FM-15 METAR"
                    })
                    
                curr += timedelta(minutes=30)
                
    return raw_dir
