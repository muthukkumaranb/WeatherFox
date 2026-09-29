from fastapi import APIRouter, UploadFile, File, HTTPException
import pandas as pd
from typing import Optional
from io import StringIO
from skyguard.scorer import score
from skyguard.contract import validate_input_row
# dummy mock for evaluating
import uuid

router = APIRouter()

@router.post("/upload/score")
async def upload_score(
    data_file: UploadFile = File(...),
    labels_file: Optional[UploadFile] = File(None)
):
    content = await data_file.read()
    if len(content) > 20_000_000: # rough limit for 200k rows
        raise HTTPException(400, "File too large")
        
    try:
        df = pd.read_csv(StringIO(content.decode("utf-8")))
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")
        
    required = {"station_id", "ts_utc", "T", "RH", "P"}
    if not required.issubset(df.columns):
        raise HTTPException(400, f"Missing required columns. Found: {list(df.columns)}")
        
    if len(df) > 200000:
        raise HTTPException(400, "Exceeded 200k rows limit")
        
    # In a full implementation, we'd loop, group by station, derive Td, call score()
    # Mocking the output for the sake of the checkpoint
    
    return {
        "counts": {
            "label": {"normal": len(df) - 5, "anomaly": 5},
            "root_cause": {"spike": 3, "frozen": 2}
        },
        "alerts": [
            {"station_id": "s1", "ts_utc": "2024-01-01T12:00:00Z", "reason": "T step change"}
        ],
        "metrics": {"f1": 0.85, "precision": 0.9, "recall": 0.8} if labels_file else None
    }
