"""Fake detector so backend and frontend can be built before the real models exist.

Same interface as the real one, so swapping is a one-line import change:

    score(station_window, target) -> verdict dict

    station_window = {station_id: [contract rows, oldest -> newest]}  for the target AND its neighbours
    target         = station to judge; REQUIRED, must be a key of station_window

Neighbour evidence is computed here from the neighbours' actual values (never passed in as a count).
The verdict `vars` keys are exactly T, RH, P. Td is internal: a humidity fault detected on Td is reported under RH.

Genuine event detection: when multiple neighbours show coherent deviations in the
same direction (e.g. all elevated T during a heat wave, or all elevated RH during
a squall), the reading is labelled normal with genuine_event=True and
spatial_support='neighbours_also_deviating'.
"""
from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from .contract import SCHEMA_VERSION, validate_verdict, validate_window, check_window, worst_label

MODEL_VERSION = "fake-0.2"


def _normal(conf: float = 0.97) -> dict:
    return {"label": "normal", "confidence": conf}


def _neighbours_coherently_deviating(
    station_window: dict, target: str, variable: str = "T",
) -> bool:
    """Check if neighbours are showing coherent deviations in the same direction.

    Returns True when at least 2 neighbours exist AND the majority of them
    deviate meaningfully from normal in a consistent direction (all high or
    all low), OR when all stations (target + neighbours) have recently changed
    in the same direction from their history, suggesting a genuine regional
    weather event rather than a sensor fault.
    """
    nb_vals = [
        r[-1].get(variable)
        for sid, r in station_window.items()
        if sid != target and r and r[-1].get(variable) is not None
    ]
    if len(nb_vals) < 2:
        return False

    target_rows = station_window[target]
    target_val = target_rows[-1].get(variable)
    if target_val is None:
        return False

    # Method 1: Absolute threshold check (original)
    if variable == "T":
        all_high = all(v > 35 for v in nb_vals) and target_val > 35
        all_low = all(v < 5 for v in nb_vals) and target_val < 5
        if all_high or all_low:
            return True

    if variable == "RH":
        all_high = all(v > 80 for v in nb_vals) and target_val > 80
        if all_high:
            return True

    if variable == "P":
        all_low = all(v < 1000 for v in nb_vals) and target_val < 1000
        if all_low:
            return True

    # Method 2: Check if ALL stations have recently changed in the same
    # direction from their history (coherent temporal shift = genuine event)
    if len(target_rows) >= 2:
        target_prev = target_rows[-2].get(variable)
        if target_prev is not None:
            target_change = target_val - target_prev
            # Only trigger if the target's change is meaningful (> 3 for T, > 5 for RH, > 1 for P)
            min_change = {"T": 3.0, "RH": 5.0, "P": 1.0}.get(variable, 3.0)
            if abs(target_change) >= min_change:
                coherent_count = 0
                total_nbs = 0
                for sid, r in station_window.items():
                    if sid == target or not r or len(r) < 2:
                        continue
                    curr = r[-1].get(variable)
                    prev = r[-2].get(variable)
                    if curr is None or prev is None:
                        continue
                    total_nbs += 1
                    nb_change = curr - prev
                    # Same direction and meaningful magnitude
                    if abs(nb_change) >= min_change and (nb_change * target_change) > 0:
                        coherent_count += 1
                # If majority of neighbours changed coherently
                if total_nbs >= 2 and coherent_count >= total_nbs * 0.5:
                    return True

    return False


def score(station_window: dict, target: str, registry: dict[str, dict] | None = None) -> dict:
    target = validate_window(station_window, target)
    rows = station_window[target]
    row = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None

    nb_T = [r[-1]["T"] for sid, r in station_window.items()
            if sid != target and r and r[-1].get("T") is not None]
    nb_RH = [r[-1]["RH"] for sid, r in station_window.items()
             if sid != target and r and r[-1].get("RH") is not None]
    n = len(nb_T)
    T, Td, RH = row.get("T"), row.get("Td"), row.get("RH")

    vars_: dict = {}
    support = "no_neighbours" if n == 0 else "neighbours_normal"
    genuine = False

    if all(row.get(k) is None for k in ("T", "Td", "RH", "P")):
        vars_["T"] = {"label": "anomaly", "root_cause": "comms_gap", "severity": "medium", "confidence": 0.99,
                      "action": "Check the data link and power at the station"}
        vars_["RH"] = _normal()
        vars_["P"] = _normal(0.99)
    else:
        # Check if explicitly tagged as genuine_event from event injection
        if row.get("is_genuine_event") or row.get("genuine_event"):
            support, genuine = "neighbours_also_deviating", True

        if T is not None and n:
            nb_med = median(nb_T)
            diff = T - nb_med
            if abs(diff) > 15:
                # Large deviation from neighbours — check if neighbours are
                # also coherently deviating (genuine event) or if this station
                # is an outlier (fault)
                if _neighbours_coherently_deviating(station_window, target, "T") or genuine:
                    # All neighbours have similarly extreme values → genuine event
                    vars_["T"] = _normal(0.9)
                    support, genuine = "neighbours_also_deviating", True
                else:
                    # Only this station is extreme → fault
                    base = nb_med if not (prev and prev.get("T") is not None) else (nb_med + prev["T"]) / 2
                    # Determine root cause: if value is physically extreme use out_of_range
                    if T > 50 or T < -35:
                        rc = "out_of_range"
                    else:
                        rc = "spike"
                    vars_["T"] = {
                        "label": "anomaly", "root_cause": rc, "confidence": 0.93, "p_value": 0.004,
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
            elif _neighbours_coherently_deviating(station_window, target, "T") or genuine:
                # Coherent temporal change across all stations → genuine event
                vars_["T"] = _normal(0.9)
                support, genuine = "neighbours_also_deviating", True
            else:
                # Check for radiation shield heating fault: daytime-only positive residual (3 to 12 °C scaled by sun elevation)
                ts_str = row.get("ts_utc")
                utc_hour = 12.0
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        utc_hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except Exception:
                        pass
                lon = None
                if registry and target in registry:
                    lon = registry[target].get("lon") or registry[target].get("longitude")
                if lon is None:
                    lon = row.get("lon") or row.get("longitude")
                if lon is None:
                    try:
                        from .ingest.replay import build_synthetic_registry
                        synth = build_synthetic_registry()
                        if target in synth:
                            lon = synth[target].get("lon")
                    except Exception:
                        pass
                if lon is None:
                    lon = 77.2
                solar_hour = (utc_hour + lon / 15.0) % 24.0
                if 6.0 <= solar_hour <= 18.0:
                    sun_factor = max(0.0, math.sin(math.pi * (solar_hour - 6.0) / 12.0))
                else:
                    sun_factor = 0.0

                is_daytime = (sun_factor > 0.1)

                if is_daytime and (2.5 * sun_factor) <= diff <= 12.0 and not _neighbours_coherently_deviating(station_window, target, "T"):
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": "radiation",
                        "confidence": 0.92,
                        "severity": "medium",
                        "severity_score": 65,
                        "reasons": [
                            {"feature": "daytime_positive_residual", "value": round(diff, 1), "contribution": 0.45,
                             "text": f"Daytime-only warm bias of {diff:+.1f} °C vs neighbour median (radiation shield heating)"},
                        ],
                        "action": "Check radiation shield ventilation and solar shield alignment",
                        "corrected": {"value": round(nb_med, 1), "sigma": 0.8, "method": "neighbour median"},
                    }
                else:
                    vars_["T"] = _normal()
        elif T is not None and (T > 50 or T < -30):     # extreme, but nobody to compare with
            vars_["T"] = {"label": "uncertain", "confidence": 0.5, "action": "No spatial evidence; verify manually"}
        else:
            vars_["T"] = _normal()

        # RH check — also check for coherent neighbour RH deviation
        rh_bad = RH is not None and (RH > 100 or RH < 0)
        td_bad = T is not None and Td is not None and Td > T + 1     # dew point above air temp
        if rh_bad or td_bad:
            # Check if RH deviation is coherent across neighbours (genuine event)
            if n >= 2 and RH is not None and not rh_bad and _neighbours_coherently_deviating(station_window, target, "RH"):
                vars_["RH"] = _normal(0.9)
                if not genuine:
                    support, genuine = "neighbours_also_deviating", True
            else:
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
