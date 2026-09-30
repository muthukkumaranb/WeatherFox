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


def _get_utc_hour(row: dict) -> int | None:
    ts = row.get("ts_utc") or row.get("timestamp_utc") or row.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, str) and len(ts) >= 13 and ts[10] == "T" and ts[11:13].isdigit():
        return int(ts[11:13])
    if isinstance(ts, datetime):
        return ts.hour
    if isinstance(ts, str):
        try:
            ts_str = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            return dt.hour
        except Exception:
            if "T" in ts:
                try:
                    time_part = ts.split("T")[1]
                    return int(time_part.split(":")[0])
                except Exception:
                    pass
    return None



def _get_station_hour_anomaly(station_rows: list[dict], variable: str, row_idx: int = -1) -> float | None:
    """Compute station's anomaly for row at row_idx relative to past expected mean for same UTC hour.

    Returns None if no past same-UTC-hour history exists.
    """
    if not station_rows:
        return None
    n_rows = len(station_rows)
    idx = row_idx if row_idx >= 0 else n_rows + row_idx
    if idx < 0 or idx >= n_rows:
        return None

    curr_row = station_rows[idx]
    curr_val = curr_row.get(variable)
    if curr_val is None:
        return None
    curr_hour = _get_utc_hour(curr_row)
    if curr_hour is None:
        return None

    s = 0.0
    c = 0
    for i in range(idx - 1, -1, -1):
        r = station_rows[i]
        if _get_utc_hour(r) == curr_hour:
            v = r.get(variable)
            if v is not None:
                s += v
                c += 1
    if c > 0:
        return curr_val - (s / c)
    return None


def _neighbours_coherently_deviating(
    station_window: dict, target: str, variable: str = "T",
) -> bool:
    """Check if target and neighbours show coherent anomalies from expected same-hour mean.

    Returns True when:
    - |target anomaly| >= 4 °C (T), 15 % (RH), 4 hPa (P)
    - >= 50 % of valid neighbours (min 2) have anomalies of the same sign and >= half target anomaly size.
    """
    target_rows = station_window.get(target, [])
    target_anomaly = _get_station_hour_anomaly(target_rows, variable)
    # Without same-hour history only temperature has a safe climatological fallback (>= 8 °C away
    # from 30 °C, e.g. 47 °C). RH and P have none: inland station pressure (~1000 hPa) or dry air
    # would look like an "event" against fixed defaults.
    no_history_fallback = variable == "T"
    if target_anomaly is None:
        if not no_history_fallback or not target_rows or target_rows[-1].get(variable) is None:
            return False
        raw_diff = target_rows[-1][variable] - 30.0
        if abs(raw_diff) < 8.0:
            return False
        target_anomaly = raw_diff

    thresholds = {"T": 4.0, "RH": 15.0, "P": 4.0}
    min_thresh = thresholds.get(variable, 4.0)
    if abs(target_anomaly) < min_thresh:
        return False

    valid_nb_anomalies = []
    for sid, r in station_window.items():
        if sid == target or not r:
            continue
        nb_anom = _get_station_hour_anomaly(r, variable)
        if nb_anom is None and no_history_fallback and r[-1].get(variable) is not None:
            nb_anom = r[-1][variable] - 30.0
        if nb_anom is not None:
            valid_nb_anomalies.append(nb_anom)

    if len(valid_nb_anomalies) < 2:
        return False

    half_target_size = 0.5 * abs(target_anomaly)
    coherent_count = 0
    for nb_anom in valid_nb_anomalies:
        if (nb_anom * target_anomaly > 0) and (abs(nb_anom) >= half_target_size):
            coherent_count += 1

    return coherent_count >= len(valid_nb_anomalies) * 0.5



def _get_station_elevation(sid: str, row: dict, registry: dict[str, dict] | None) -> float:
    if registry and sid in registry:
        for k in ("elevation", "elev_m", "elev"):
            if registry[sid].get(k) is not None:
                try:
                    return float(registry[sid][k])
                except (ValueError, TypeError):
                    pass
    for k in ("elevation", "elev_m", "elev"):
        if row.get(k) is not None:
            try:
                return float(row[k])
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_sun_factor(ts_str: str | None, lon: float = 77.2) -> tuple[float, float, bool]:
    utc_hour = 12.0
    if ts_str:
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            utc_hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        except Exception:
            pass
    solar_hour = (utc_hour + lon / 15.0) % 24.0
    if 6.0 <= solar_hour <= 18.0:
        sun_factor = max(0.0, math.sin(math.pi * (solar_hour - 6.0) / 12.0))
    else:
        sun_factor = 0.0
    return utc_hour, sun_factor, (sun_factor > 0.3)


def score(station_window: dict, target: str, registry: dict[str, dict] | None = None) -> dict:
    target = validate_window(station_window, target)
    rows = station_window[target]
    row = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None

    # Calculate elevation-corrected temperature and anomalies for neighbours
    target_elev = _get_station_elevation(target, row, registry)
    target_anom = _get_station_hour_anomaly(rows, "T")
    T, Td, RH, P = row.get("T"), row.get("Td"), row.get("RH"), row.get("P")

    lon = None
    if registry and target in registry:
        lon = registry[target].get("lon") or registry[target].get("longitude")
    if lon is None:
        lon = row.get("lon") or row.get("longitude")
    if lon is None:
        lon = 77.2

    nb_anomalies = []
    nb_vals_corr = []
    for sid, r in station_window.items():
        if sid == target or not r or r[-1].get("T") is None:
            continue
        nb_row = r[-1]
        nb_val = nb_row["T"]
        nb_elev = _get_station_elevation(sid, nb_row, registry)
        delta_elev = target_elev - nb_elev
        nb_val_corr = nb_val - 0.0065 * delta_elev
        nb_vals_corr.append(nb_val_corr)

        nb_anom = _get_station_hour_anomaly(r, "T")
        if nb_anom is not None:
            nb_anomalies.append(nb_anom)

    n = len(nb_vals_corr)
    vars_: dict = {}
    support = "no_neighbours" if n == 0 else "neighbours_normal"
    genuine = False

    # Helper to check if neighbours vary over the window
    def _neighbours_vary(var_name: str, req_count: int) -> bool:
        if n == 0:
            return False
        variations = []
        for sid, r in station_window.items():
            if sid == target or not r:
                continue
            recent = [x.get(var_name) for x in r[-req_count:] if x.get(var_name) is not None]
            if len(recent) >= 2:
                variations.append(max(recent) - min(recent))
        if not variations:
            return False
        return median(variations) > 0.1

    # Helper to check frozen readings in tail of rows (same value +-0.05 for >= 6 consecutive hourly or >= 4 for 3-hourly while neighbours vary)
    def _check_frozen(var_name: str, tol: float = 0.05) -> bool:
        if len(rows) < 4:
            return False
        curr = row.get(var_name)
        if curr is None:
            return False
        cadence = row.get("cadence_min", 60)
        req_count = 4 if cadence >= 120 else 6
        c = 0
        for r in reversed(rows):
            v = r.get(var_name)
            if v is not None and abs(v - curr) <= tol:
                c += 1
            else:
                break
        if c >= req_count and _neighbours_vary(var_name, req_count):
            return True
        return False

    if all(row.get(k) is None for k in ("T", "Td", "RH", "P")):
        vars_["T"] = {"label": "anomaly", "root_cause": "comms_gap", "severity": "medium", "confidence": 0.99,
                      "action": "Check the data link and power at the station"}
        vars_["RH"] = _normal()
        vars_["P"] = _normal(0.99)
    else:
        # Genuine events are inferred ONLY from the data (neighbours deviating together);
        # the scorer never reads injection/ground-truth tags from the row.

        if T is not None:
            if n > 0:
                nb_med_val = median(nb_vals_corr)
                nb_med_anom = median(nb_anomalies) if nb_anomalies else 0.0
                if n >= 2:
                    nb_spread = max(0.5, (max(nb_anomalies) - min(nb_anomalies)) if nb_anomalies else (max(nb_vals_corr) - min(nb_vals_corr)))
                else:
                    nb_spread = 0.5
                thresh = min(8.0, max(4.0, 3.0 * nb_spread))
                diff_anom = T - nb_med_val
            else:
                nb_med_val = T
                nb_med_anom = 0.0
                nb_spread = 0.5
                thresh = 4.0
                diff_anom = 0.0

            # 1. Extreme out-of-range checks FIRST (T >= 55 °C or T <= -40 °C)
            if T >= 55.0 or T <= -40.0:
                if n == 0:
                    vars_["T"] = {"label": "uncertain", "confidence": 0.5, "action": "No spatial evidence; verify manually"}
                    support = "no_neighbours"
                else:
                    vars_["T"] = {
                        "label": "anomaly", "root_cause": "out_of_range", "confidence": 0.98,
                        "severity": "high", "severity_score": 95,
                        "reasons": [{"feature": "T_absolute", "value": round(T, 1), "contribution": 0.9, "text": f"Temperature {T} °C exceeds physical limit (55 °C or <= -40 °C)"}],
                        "action": "Sensor reading out of range; inspect hardware",
                        "corrected": {"value": round(nb_med_val, 1), "sigma": 0.9, "method": "neighbour median"},
                    }
                    support = "neighbours_normal"
                genuine = False
            # 2. Frozen check (>= 6 consecutive hourly or >= 4 3-hourly readings)
            elif _check_frozen("T"):
                is_fog = RH is not None and RH >= 97.0
                if is_fog:
                    vars_["T"] = {
                        "label": "uncertain",
                        "root_cause": "frozen",
                        "confidence": 0.70,
                        "severity": "low",
                        "reasons": [{"feature": "frozen_reads", "value": round(T, 2), "contribution": 0.5, "text": f"Temperature value {T} °C unchanged during fog (RH >= 97%)"}],
                        "action": "Persistent reading during fog; monitor for change",
                    }
                else:
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": "frozen",
                        "confidence": 0.90,
                        "severity": "medium",
                        "severity_score": 75,
                        "reasons": [{"feature": "frozen_reads", "value": round(T, 2), "contribution": 0.8, "text": f"Temperature value {T} °C frozen for 6+ consecutive readings while neighbours vary"}],
                        "action": "Sensor output frozen; check hardware and transducer",
                        "corrected": {"value": round(nb_med_val, 1) if n > 0 else 30.0, "sigma": 0.8, "method": "neighbour median"},
                    }
            elif _neighbours_coherently_deviating(station_window, target, "T") or (genuine and abs(diff_anom) < thresh):
                vars_["T"] = _normal(0.9)
                support, genuine = "neighbours_also_deviating", True
            elif abs(diff_anom) >= 3.0 or abs(diff_anom) > thresh:
                # Evaluate Radiation vs Offset vs Spike
                utc_h, sun_factor, is_daytime = _get_sun_factor(row.get("ts_utc"), lon)
                daytime_warm_count = 0
                night_diffs = []

                for r_idx in range(len(rows) - 1, -1, -1):
                    r = rows[r_idx]
                    r_ts = r.get("ts_utc")
                    _, r_sf, r_day = _get_sun_factor(r_ts, lon)
                    r_val = r.get("T")
                    if r_val is None:
                        continue
                    r_diff = r_val - nb_med_val

                    if r_day:
                        if r_diff >= 3.0:
                            daytime_warm_count += 1
                    else:
                        night_diffs.append(r_diff)

                recent_night_diff = median(night_diffs) if night_diffs else None
                has_night_bias = (recent_night_diff is not None and recent_night_diff >= 1.5)
                is_offset = (has_night_bias and diff_anom >= 1.5) or (len(rows) >= 3 and has_night_bias and abs(diff_anom) >= 3.0)
                night_ok = (not has_night_bias)
                is_rad_anomaly = is_daytime and (3.0 <= diff_anom < 8.0) and (daytime_warm_count >= 2) and night_ok
                is_rad_uncertain = is_daytime and (3.0 <= diff_anom < 8.0) and (daytime_warm_count <= 1) and night_ok

                base = nb_med_val if not (prev and prev.get("T") is not None) else (nb_med_val + prev["T"]) / 2

                if is_offset:
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": "offset",
                        "confidence": 0.93,
                        "severity": "medium",
                        "severity_score": 75,
                        "reasons": [
                            {"feature": "persistent_bias", "value": round(diff_anom, 1), "contribution": 0.6,
                             "text": f"Persistent temperature offset of {diff_anom:+.1f} °C across day and night"},
                        ],
                        "action": "Recalibrate sensor zero/span offset",
                        "corrected": {"value": round(base, 1), "sigma": 0.8, "method": "neighbour median"},
                    }
                elif is_rad_anomaly:
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": "radiation",
                        "confidence": 0.92,
                        "severity": "medium",
                        "severity_score": 65,
                        "reasons": [
                            {"feature": "daytime_positive_residual", "value": round(diff_anom, 1), "contribution": 0.45,
                             "text": f"Daytime-only warm anomaly of {diff_anom:+.1f} °C over 2+ consecutive readings (radiation shield heating)"},
                        ],
                        "action": "Check radiation shield ventilation and solar shield alignment",
                        "corrected": {"value": round(nb_med_val, 1), "sigma": 0.8, "method": "neighbour median"},
                    }
                elif is_rad_uncertain:
                    vars_["T"] = {
                        "label": "uncertain",
                        "root_cause": "radiation",
                        "confidence": 0.70,
                        "severity": "low",
                        "reasons": [
                            {"feature": "single_daytime_warm_reading", "value": round(diff_anom, 1), "contribution": 0.45,
                             "text": f"Single daytime warm anomaly of {diff_anom:+.1f} °C vs neighbour median"},
                        ],
                        "action": "Monitor next daytime reading for persistent radiation shield heating",
                    }
                elif abs(diff_anom) > thresh and n >= 2:
                    rc = "out_of_range" if (T >= 55 or T <= -40) else "spike"
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": rc,
                        "confidence": 0.93,
                        "p_value": 0.004,
                        "severity": "high",
                        "severity_score": 82,
                        "reasons": [
                            {"feature": "T_resid_neighbours", "value": round(diff_anom, 1), "contribution": 0.41,
                             "text": f"Temperature anomaly is {diff_anom:+.1f} °C from neighbours"},
                        ],
                        "action": "Inspect the T sensor and wiring; value excluded from products",
                        "corrected": {"value": round(base, 1), "sigma": 0.9, "method": "neighbour median"},
                    }
                else:
                    vars_["T"] = _normal()
            else:
                vars_["T"] = _normal()
        else:
            vars_["T"] = _normal()

        # RH check — out_of_range FIRST, then frozen, then coherent neighbour deviation
        rh_out_of_range = RH is not None and (RH < 0.0 or RH > 100.5)
        td_bad = T is not None and Td is not None and Td > T + 1.0

        if rh_out_of_range or td_bad:
            vars_["RH"] = {
                "label": "anomaly", "root_cause": "out_of_range", "severity": "medium", "confidence": 0.9,
                "action": "Check the humidity probe"
            }
        elif _check_frozen("RH"):
            is_fog = RH is not None and RH >= 97.0
            if is_fog:
                vars_["RH"] = {
                    "label": "uncertain",
                    "root_cause": "frozen",
                    "confidence": 0.70,
                    "severity": "low",
                    "action": "Persistent RH during fog; monitor for change",
                }
            else:
                vars_["RH"] = {
                    "label": "anomaly",
                    "root_cause": "frozen",
                    "confidence": 0.90,
                    "severity": "medium",
                    "action": "RH sensor output frozen; inspect humidity sensor",
                }
        elif n >= 2 and RH is not None and _neighbours_coherently_deviating(station_window, target, "RH"):
            vars_["RH"] = _normal(0.9)
            support, genuine = "neighbours_also_deviating", True
        else:
            vars_["RH"] = _normal()

        # P check — out_of_range FIRST for SLP (850-1085 hPa), then frozen, then coherent neighbour deviation
        p_type = row.get("P_type", "slp")
        p_out_of_range = P is not None and (p_type != "station") and (P < 850.0 or P > 1085.0)
        if p_out_of_range:
            vars_["P"] = {
                "label": "anomaly", "root_cause": "out_of_range", "severity": "high", "confidence": 0.98,
                "action": "Pressure reading out of physical SLP range"
            }
        elif _check_frozen("P"):
            vars_["P"] = {
                "label": "anomaly", "root_cause": "frozen", "severity": "medium", "confidence": 0.90,
                "action": "Barometer output frozen; inspect pressure sensor"
            }
        elif n >= 2 and P is not None and _neighbours_coherently_deviating(station_window, target, "P"):
            vars_["P"] = _normal(0.9)
            support, genuine = "neighbours_also_deviating", True
        else:
            vars_["P"] = _normal(0.99)

    label = worst_label(x["label"] for x in vars_.values())

    # Anomaly or uncertain readings are NEVER genuine events
    if label != "normal":
        genuine = False
        if support == "neighbours_also_deviating":
            support = "neighbours_normal" if n > 0 else "no_neighbours"

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

