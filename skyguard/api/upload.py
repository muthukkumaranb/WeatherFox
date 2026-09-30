"""Upload & score endpoint for CSV data files.  Owner: Person C.

Accepts a CSV with columns: station_id, ts_utc, T, RH, P
Optional: Td, lat, lon, source
Also accepts a 'source' form field (default: imd_wis2).

Each valid row is:
  1. Validated via skyguard.contract.validate_input_row
  2. Checked by skyguard.ingest.rule_gate.check (FAIL -> anomaly, root_cause out_of_range)
  3. Scored by skyguard.scorer.score with station window context

Returns counts of labels and root_causes, plus alerts and invalid_count.
"""
from __future__ import annotations

import csv
import io
import math
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from skyguard.contract import ContractError, validate_input_row
from skyguard.ingest.rule_gate import check as rule_gate_check
from skyguard.scorer import score

router = APIRouter()


def _parse_float(val: str) -> Optional[float]:
    """Parse float or return None for empty/nan."""
    if val is None:
        return None
    s = val.strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@router.post("/upload/score")
async def upload_score(
    data_file: UploadFile = File(...),
    labels_file: Optional[UploadFile] = File(None),
    source: str = Form("imd_wis2"),
):
    """Score a CSV upload of weather readings."""
    content = await data_file.read()
    if len(content) > 20_000_000:
        raise HTTPException(400, "File too large (>20 MB)")

    try:
        text = content.decode("utf-8-sig")  # handle BOM
    except Exception as e:
        raise HTTPException(400, f"Cannot decode file: {e}")

    try:
        reader = csv.DictReader(io.StringIO(text))
        all_rows = list(reader)
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")

    required_cols = {"station_id", "ts_utc", "T", "RH", "P"}
    if not all_rows:
        raise HTTPException(400, "CSV is empty or has no data rows")

    actual_cols = set(all_rows[0].keys()) if all_rows else set()
    missing = required_cols - actual_cols
    if missing:
        raise HTTPException(400, f"Missing required columns: {sorted(missing)}")

    if len(all_rows) > 200_000:
        raise HTTPException(400, "Exceeded 200k rows limit")

    # Determine source column handling
    has_source_col = "source" in actual_cols

    invalid_rows: list[dict] = []
    valid_rows: list[dict] = []

    for i, raw in enumerate(all_rows):
        # Build the contract row
        t_val = _parse_float(raw.get("T"))
        rh_val = _parse_float(raw.get("RH"))
        p_val = _parse_float(raw.get("P"))
        td_raw = _parse_float(raw.get("Td"))

        # Compute Td if missing
        if td_raw is None and t_val is not None and rh_val is not None:
            td_val = t_val - ((100.0 - rh_val) / 5.0)
        else:
            td_val = td_raw

        # Determine source
        if has_source_col:
            row_source = (raw.get("source") or "").strip() or source
        else:
            row_source = source

        # Parse cadence_min
        cadence_raw = _parse_float(raw.get("cadence_min"))
        cadence_min = int(cadence_raw) if cadence_raw is not None else 60

        row_dict = {
            "schema_v": "1.0",
            "station_id": str(raw.get("station_id", "")).strip(),
            "ts_utc": str(raw.get("ts_utc", "")).strip(),
            "T": t_val,
            "Td": td_val,
            "RH": rh_val,
            "P": p_val,
            "P_type": "slp",
            "cadence_min": cadence_min,
            "source": row_source,
        }

        try:
            validated = validate_input_row(row_dict)
            valid_rows.append(validated)
        except (ContractError, Exception) as e:
            invalid_rows.append({"row": i, "reason": str(e)})

    # Build per-station windows and process chronologically
    station_windows: dict[str, list[dict]] = {}
    counts: dict = {"label": {}, "root_cause": {}}
    alerts: list[dict] = []

    # Sort valid rows by station then by timestamp
    valid_rows.sort(key=lambda r: (r["station_id"], r["ts_utc"]))

    for r in valid_rows:
        sid = r["station_id"]
        if sid not in station_windows:
            station_windows[sid] = []

        # Run rule_gate first
        window_for_gate = station_windows[sid] + [r]
        cadence = r.get("cadence_min", 60)
        gate_result = rule_gate_check(window_for_gate, cadence_min=cadence)

        gate_failed = any(
            gate_result.get(v, {}).get("fail", False) for v in ("T", "RH", "P")
        )

        if gate_failed:
            # Rule gate hard fail → anomaly with out_of_range
            # Find the failing variable's cause
            causes = [
                gate_result[v]["root_cause"]
                for v in ("T", "RH", "P")
                if gate_result.get(v, {}).get("fail", False)
            ]
            root_cause = causes[0] if causes else "out_of_range"

            label = "anomaly"
            counts["label"]["anomaly"] = counts["label"].get("anomaly", 0) + 1
            counts["root_cause"][root_cause] = counts["root_cause"].get(root_cause, 0) + 1

            if len(alerts) < 200:
                failing_var_reason = next(
                    (gate_result[v]["reason"] for v in ("T", "RH", "P")
                     if gate_result.get(v, {}).get("fail", False)),
                    "rule gate failure"
                )
                alerts.append({
                    "station_id": sid,
                    "ts_utc": r["ts_utc"],
                    "reason": failing_var_reason,
                    "root_cause": root_cause,
                    "source": "rule_gate",
                })
        else:
            # Add row to window then run scorer
            station_windows[sid].append(r)

            try:
                verdict = score(station_windows, sid)
            except Exception:
                # Fallback: treat as normal if scorer fails
                verdict = {"label": "normal"}

            label = verdict.get("label", "normal")
            counts["label"][label] = counts["label"].get(label, 0) + 1

            if label == "anomaly":
                vars_v = verdict.get("vars", {})
                rc_candidates = [
                    vars_v[v].get("root_cause", "unknown")
                    for v in vars_v
                    if vars_v[v].get("label") == "anomaly"
                ]
                root_cause = rc_candidates[0] if rc_candidates else "unknown"
                counts["root_cause"][root_cause] = counts["root_cause"].get(root_cause, 0) + 1

                if len(alerts) < 200:
                    # The verdict has no top-level "reason"; use the flagged variable's own explanation.
                    reason_text = next(
                        (vars_v[v]["reasons"][0].get("text")
                         for v in vars_v
                         if vars_v[v].get("label") == "anomaly" and vars_v[v].get("reasons")),
                        None,
                    )
                    alerts.append({
                        "station_id": sid,
                        "ts_utc": r["ts_utc"],
                        "reason": reason_text or verdict.get("reason", "anomaly detected"),
                        "root_cause": root_cause,
                        "source": "scorer",
                    })

    return {
        "counts": counts,
        "invalid_count": len(invalid_rows),
        "n_valid": len(valid_rows),
        "alerts": alerts,
        "metrics": None,
    }
