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
    if target_anomaly is None:
        # Fallback for single-row window (e.g. heatwave preset test): compute deviation from 30 °C / 60 % / 1013 hPa
        curr_val = target_rows[-1].get(variable) if target_rows else None
        if curr_val is None:
            return False
        defaults = {"T": 30.0, "RH": 60.0, "P": 1013.0}
        default_val = defaults.get(variable, 30.0)
        raw_diff = curr_val - default_val
        # Require substantial deviation (>= 8.0 °C / 20 % / 8 hPa) from climatology default to trigger without same-hour history
        big_diff_thresh = {"T": 8.0, "RH": 20.0, "P": 8.0}.get(variable, 8.0)
        if abs(raw_diff) < big_diff_thresh:
            return False
        target_anomaly = raw_diff

    thresholds = {"T": 4.0, "RH": 15.0, "P": 4.0}
    min_thresh = thresholds.get(variable, 4.0)
    if abs(target_anomaly) < min_thresh:
        return False

    valid_nb_anomalies = []
    defaults = {"T": 30.0, "RH": 60.0, "P": 1013.0}
    default_val = defaults.get(variable, 30.0)
    for sid, r in station_window.items():
        if sid == target or not r:
            continue
        nb_anom = _get_station_hour_anomaly(r, variable)
        if nb_anom is None:
            v_val = r[-1].get(variable)
            if v_val is not None:
                nb_anom = v_val - default_val
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
    T, Td, RH = row.get("T"), row.get("Td"), row.get("RH")

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

    if all(row.get(k) is None for k in ("T", "Td", "RH", "P")):
        vars_["T"] = {"label": "anomaly", "root_cause": "comms_gap", "severity": "medium", "confidence": 0.99,
                      "action": "Check the data link and power at the station"}
        vars_["RH"] = _normal()
        vars_["P"] = _normal(0.99)
    else:
        # Check if explicitly tagged as genuine_event from event injection
        if row.get("is_genuine_event") or row.get("genuine_event"):
            support, genuine = "neighbours_also_deviating", True

        if T is not None:
            if n > 0:
                nb_med_val = median(nb_vals_corr)
                nb_med_anom = median(nb_anomalies) if nb_anomalies else 0.0
                if n >= 2:
                    nb_spread = max(0.5, (max(nb_anomalies) - min(nb_anomalies)) if nb_anomalies else (max(nb_vals_corr) - min(nb_vals_corr)))
                else:
                    nb_spread = 0.5
                thresh = max(4.0, 3.0 * nb_spread)
                if target_anom is not None:
                    diff_anom = target_anom - nb_med_anom
                else:
                    diff_anom = T - nb_med_val
            else:
                nb_med_val = T
                nb_med_anom = 0.0
                nb_spread = 0.5
                thresh = 4.0
                diff_anom = 0.0

            # 1. Extreme out-of-range checks (e.g. 55 °C preset)
            if T >= 55.0:
                if n == 0:
                    vars_["T"] = {"label": "uncertain", "confidence": 0.5, "action": "No spatial evidence; verify manually"}
                else:
                    vars_["T"] = {
                        "label": "anomaly", "root_cause": "out_of_range", "confidence": 0.98,
                        "severity": "high", "severity_score": 95,
                        "reasons": [{"feature": "T_absolute", "value": round(T, 1), "contribution": 0.9, "text": f"Temperature {T} °C exceeds physical limit (55 °C)"}],
                        "action": "Sensor reading out of range; inspect hardware",
                        "corrected": {"value": round(nb_med_val, 1), "sigma": 0.9, "method": "neighbour median"},
                    }
            elif _neighbours_coherently_deviating(station_window, target, "T") or genuine:
                vars_["T"] = _normal(0.9)
                support, genuine = "neighbours_also_deviating", True
            elif abs(diff_anom) > 15 and n >= 2:
                base = nb_med_val if not (prev and prev.get("T") is not None) else (nb_med_val + prev["T"]) / 2
                rc = "out_of_range" if (T > 50 or T < -35) else "spike"
                vars_["T"] = {
                    "label": "anomaly", "root_cause": rc, "confidence": 0.93, "p_value": 0.004,
                    "severity": "high", "severity_score": 82,
                    "reasons": [
                        {"feature": "T_resid_neighbours", "value": round(diff_anom, 1), "contribution": 0.41,
                         "text": f"Temperature anomaly is {diff_anom:+.1f} °C from neighbours"},
                    ],
                    "action": "Inspect the T sensor and wiring; value excluded from products",
                    "corrected": {"value": round(base, 1), "sigma": 0.9, "method": "neighbour median"},
                }
            else:
                # Evaluate Radiation Rule
                utc_h, sun_factor, is_daytime = _get_sun_factor(row.get("ts_utc"), lon)
                daytime_warm_count = 0
                recent_night_diff = None

                for r_idx in range(len(rows) - 1, -1, -1):
                    r = rows[r_idx]
                    r_ts = r.get("ts_utc")
                    _, r_sf, r_day = _get_sun_factor(r_ts, lon)
                    r_val = r.get("T")
                    if r_val is None:
                        continue
                    r_anom = _get_station_hour_anomaly(rows, "T", row_idx=r_idx)
                    if r_anom is not None:
                        r_diff = r_anom - (nb_med_anom if nb_anomalies else 0.0)
                    else:
                        r_diff = r_val - nb_med_val

                    if r_day:
                        if r_diff >= 3.0:
                            daytime_warm_count += 1
                        else:
                            break
                    else:
                        if recent_night_diff is None:
                            recent_night_diff = r_diff

                night_ok = (recent_night_diff is None or recent_night_diff < 1.0)
                is_rad_anomaly = is_daytime and (diff_anom >= 3.0) and (daytime_warm_count >= 2) and night_ok
                is_rad_uncertain = is_daytime and (diff_anom >= 3.0) and (daytime_warm_count <= 1)

                if is_rad_anomaly:
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
                    rc = "out_of_range" if (T > 50 or T < -35) else "spike"
                    vars_["T"] = {
                        "label": "anomaly",
                        "root_cause": rc,
                        "confidence": 0.91,
                        "severity": "medium",
                        "reasons": [
                            {"feature": "elevation_corrected_anomaly_diff", "value": round(diff_anom, 1), "contribution": 0.4,
                             "text": f"Elevation-corrected anomaly diff {diff_anom:+.1f} °C exceeds threshold {thresh:.1f} °C"},
                        ],
                        "action": "Inspect temperature sensor",
                        "corrected": {"value": round(nb_med_val, 1), "sigma": 0.9, "method": "neighbour median"},
                    }
                elif T > 50 or T < -30:
                    vars_["T"] = {"label": "uncertain", "confidence": 0.5, "action": "No spatial evidence; verify manually"}
                else:
                    vars_["T"] = _normal()
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

