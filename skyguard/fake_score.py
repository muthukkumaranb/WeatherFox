"""Fake detector so backend and frontend can be built before the real models exist.

Same interface as the real one, so swapping is a one-line import change:

    score(station_window, target) -> verdict dict

    station_window = {station_id: [contract rows, oldest -> newest]}  for the target AND its neighbours
    target         = station to judge; REQUIRED, must be a key of station_window

Neighbour evidence is computed here from the neighbours' actual values (never passed in as a count).
The verdict `vars` keys are exactly T, RH, P. Td is internal: a humidity fault detected on Td is reported under RH.
"""
from __future__ import annotations

from statistics import median

from .contract import SCHEMA_VERSION, validate_verdict, validate_window, check_window, worst_label

MODEL_VERSION = "fake-0.2"


def _normal(conf: float = 0.97) -> dict:
    return {"label": "normal", "confidence": conf}


def score(station_window: dict, target: str) -> dict:
    if isinstance(station_window, dict) and "rows" in station_window and not station_window["rows"]:
        return {
            "score": 0.0,
            "severity": "NONE",
            "event_type": "NORMAL",
            "confidence": 1.0,
            "is_anomaly": False,
            "corrected_reading": None,
            "message": "Empty window",
        }
    target = validate_window(station_window, target)
    rows = station_window[target]
    row = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None

    nb_T = [r[-1]["T"] for sid, r in station_window.items()
            if sid != target and r and r[-1].get("T") is not None]
    n = len(nb_T)
    T, Td, RH = row.get("T"), row.get("Td"), row.get("RH")

    vars_: dict = {}
    support = "no_neighbours" if n == 0 else "neighbours_normal"
    genuine = False

    if all(row.get(k) is None for k in ("T", "Td", "RH", "P")):
        vars_["T"] = {"label": "anomaly", "root_cause": "comms_gap", "severity": "medium", "confidence": 0.99,
                      "action": "Check the data link and power at the station"}
    else:
        if T is not None and n:
            nb_med = median(nb_T)
            diff = T - nb_med
            if abs(diff) > 15:
                base = nb_med if not (prev and prev.get("T") is not None) else (nb_med + prev["T"]) / 2
                vars_["T"] = {
                    "label": "anomaly", "root_cause": "spike", "confidence": 0.93, "p_value": 0.004,
                    "severity": "high", "severity_score": 82,
                    "reasons": [
                        {"feature": "T_resid_neighbours", "value": round(diff, 1), "contribution": 0.41,
                         "text": f"Temperature is {diff:+.1f} °C from the median of {n} neighbours"},
                        {"feature": "neighbour_agreement", "value": float(n), "contribution": 0.33,
                         "text": f"{n} neighbours show normal values"},
                    ],
                    "action": "Inspect the T sensor and wiring; value excluded from products",
                    "corrected": {"value": round(base, 1), "sigma": 0.9, "method": "neighbour median + last good blend"},
                }
            elif T > 45:                               # hot everywhere: a real event, not a fault
                vars_["T"] = _normal(0.9)
                support, genuine = "neighbours_also_deviating", True
            else:
                vars_["T"] = _normal()
        elif T is not None and (T > 50 or T < -30):     # extreme, but nobody to compare with
            vars_["T"] = {"label": "uncertain", "confidence": 0.5, "action": "No spatial evidence; verify manually"}
        else:
            vars_["T"] = _normal()

        rh_bad = RH is not None and (RH > 100 or RH < 0)
        td_bad = T is not None and Td is not None and Td > T + 1     # dew point above air temp
        if rh_bad or td_bad:
            vars_["RH"] = {"label": "anomaly", "root_cause": "out_of_range", "severity": "medium", "confidence": 0.9,
                           "action": "Check the humidity probe"}
        else:
            vars_["RH"] = _normal()
        vars_["P"] = _normal(0.99)

    label = worst_label(x["label"] for x in vars_.values())
    verdict = {
        "schema_v": SCHEMA_VERSION,
        "station_id": target,
        "ts_utc": row["ts_utc"],
        "phase": "final",
        "label": label,
        "model_version": MODEL_VERSION,
        "spatial_support": support,
        "n_neighbours": n,
        "genuine_event": genuine and label == "normal",
        "vars": vars_,
    }
    return validate_verdict(verdict)
