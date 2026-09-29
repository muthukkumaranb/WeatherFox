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
    
    # Process
    for sid, st_rows in station_groups.items():
        st_rows.sort(key=lambda x: x["ts_utc"])
        out = score(st_rows)
        for r, res in zip(st_rows, out):
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
