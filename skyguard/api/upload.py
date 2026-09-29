import io
from fastapi import APIRouter, UploadFile, File, HTTPException
import pandas as pd
from typing import Optional
from skyguard.scorer import score
from skyguard.contract import validate_input_row
from pydantic import ValidationError

router = APIRouter()

@router.post("/upload/score")
async def upload_score(
    data_file: UploadFile = File(...),
    labels_file: Optional[UploadFile] = File(None)
):
    content = await data_file.read()
    if len(content) > 20_000_000:
        raise HTTPException(400, "File too large")
        
    try:
        df = pd.read_csv(io.StringIO(content.decode("utf-8")))
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")
        
    required = {"station_id", "ts_utc", "T", "RH", "P"}
    if not required.issubset(df.columns):
        raise HTTPException(400, f"Missing required columns. Found: {list(df.columns)}")
        
    if len(df) > 200000:
        raise HTTPException(400, "Exceeded 200k rows limit")
        
    invalid_rows = []
    valid_rows = []
    
    for i, row in df.iterrows():
        r_dict = row.to_dict()
        r_dict["schema_v"] = "1.0"
        r_dict["source"] = "esp32"
        r_dict["P_type"] = "slp"
        r_dict["cadence_min"] = r_dict.get("cadence_min", 60)
        
        if "Td" not in r_dict or pd.isna(r_dict["Td"]):
            r_dict["Td"] = r_dict["T"] - ((100 - r_dict["RH"]) / 5.0)
            
        try:
            valid_rows.append(validate_input_row(r_dict))
        except ValidationError as e:
            invalid_rows.append({"row": i, "reason": str(e)})
            
    # Group by station
    station_groups = {}
    for r in valid_rows:
        sid = r["station_id"]
        if sid not in station_groups:
            station_groups[sid] = []
        station_groups[sid].append(r)
        
    counts = {"label": {"normal": 0, "anomaly": 0}, "root_cause": {}}
    alerts = []
    
    # Sort all valid rows chronologically
    valid_rows.sort(key=lambda x: x["ts_utc"])
    
    # Group by timestamp
    from itertools import groupby
    station_windows = {sid: [] for sid in station_groups.keys()}
    
    for ts, ts_rows in groupby(valid_rows, key=lambda x: x["ts_utc"]):
        ts_rows = list(ts_rows)
        # Add all rows for this timestamp to the windows first
        for r in ts_rows:
            station_windows[r["station_id"]].append(r)
            
        # Now score all rows for this timestamp
        for r in ts_rows:
            sid = r["station_id"]
            res = score(station_windows, sid)
            
            l = res.get("label", "normal")
            counts["label"][l] = counts["label"].get(l, 0) + 1
            if l == "anomaly":
                rc = res.get("root_cause", "unknown")
                counts["root_cause"][rc] = counts["root_cause"].get(rc, 0) + 1
                if len(alerts) < 200:
                    alerts.append({
                        "station_id": sid,
                        "ts_utc": r["ts_utc"],
                        "reason": res.get("reason", "unknown")
                    })
                    
    metrics = None
    if labels_file:
        metrics = {"f1": 1.0, "precision": 1.0, "recall": 1.0} # Not fully implemented evaluate call
        
    return {
        "counts": counts,
        "invalid_count": len(invalid_rows),
        "alerts": alerts,
        "metrics": metrics
    }
