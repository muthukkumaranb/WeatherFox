"""Baselines: rule-gate-only, z-score, Isolation Forest. Owner: Person B.

Generates contract-compliant verdict records for evaluation comparisons.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
from typing import Sequence

from skyguard.ingest import rule_gate

try:
    from sklearn.ensemble import IsolationForest
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


def _parse_dt(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _make_verdict_record(
    station_id: str,
    ts_utc: str,
    overall_label: str,
    var_results: dict[str, dict],
    model_version: str = "baseline_v1",
) -> dict:
    vars_verdict = {}
    for var in ("T", "RH", "P"):
        if var in var_results:
            info = var_results[var]
            vars_verdict[var] = {
                "label": info.get("label", "normal"),
                "root_cause": info.get("root_cause"),
                "prob": float(info.get("prob", 0.0 if info.get("label", "normal") == "normal" else 0.95)),
                "support_count": int(info.get("support_count", 0)),
            }
        else:
            vars_verdict[var] = {
                "label": "normal",
                "root_cause": None,
                "prob": 0.0,
                "support_count": 0,
            }

    return {
        "schema_v": "1.0",
        "station_id": station_id,
        "ts_utc": ts_utc,
        "phase": "final",
        "label": overall_label,
        "model_version": model_version,
        "spatial_support": "no_neighbours",
        "n_neighbours": 0,
        "genuine_event": False,
        "vars": vars_verdict,
    }


def rules_baseline(rows: list[dict], out_path: str | Path | None = None) -> list[dict]:
    """Rule-gate baseline detector. Returns list of contract-compliant verdict dicts."""
    # Group rows by station
    by_station: dict[str, list[dict]] = {}
    for r in rows:
        st = r["station_id"]
        by_station.setdefault(st, []).append(r)

    verdicts = []
    for st, st_rows in by_station.items():
        st_rows_sorted = sorted(st_rows, key=lambda x: x["ts_utc"])
        for i in range(len(st_rows_sorted)):
            window = st_rows_sorted[max(0, i - 10): i + 1]
            rg_res = rule_gate.check(window)
            
            var_results = {}
            has_anomaly = False
            has_uncertain = False

            for var in ("T", "RH", "P"):
                info = rg_res.get(var, {})
                if info.get("fail"):
                    has_anomaly = True
                    rc = info.get("cause") or info.get("root_cause") or "out_of_range"
                    var_results[var] = {"label": "anomaly", "root_cause": rc, "prob": 0.99}
                elif info.get("suspect"):
                    has_uncertain = True
                    rc = info.get("cause") or info.get("root_cause") or "frozen"
                    var_results[var] = {"label": "uncertain", "root_cause": rc, "prob": 0.60}
                else:
                    var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}

            overall = "anomaly" if has_anomaly else ("uncertain" if has_uncertain else "normal")
            cur_row = st_rows_sorted[i]
            verdict = _make_verdict_record(st, cur_row["ts_utc"], overall, var_results, model_version="baseline_rules")
            verdicts.append(verdict)

    if out_path:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")

    return verdicts


def zscore_baseline(
    rows: list[dict],
    train_rows: list[dict] | None = None,
    out_path: str | Path | None = None,
    z_threshold: float = 4.0,
) -> list[dict]:
    """Z-score baseline detector against per-station month x hour climatology."""
    fit_data = train_rows if train_rows is not None else rows
    
    # Calculate climatology: (station_id, month, hour) -> {var: (sum, sum_sq, count)}
    stats: dict[tuple[str, int, int], dict[str, list[float]]] = {}
    for r in fit_data:
        st = r["station_id"]
        dt = _parse_dt(r["ts_utc"])
        key = (st, dt.month, dt.hour)
        if key not in stats:
            stats[key] = {"T": [0.0, 0.0, 0], "RH": [0.0, 0.0, 0], "P": [0.0, 0.0, 0]}
        
        for var in ("T", "RH", "P"):
            val = r.get(var)
            if val is not None and not math.isnan(val):
                stats[key][var][0] += val
                stats[key][var][1] += val * val
                stats[key][var][2] += 1

    climatology: dict[tuple[str, int, int], dict[str, tuple[float, float]]] = {}
    for key, var_map in stats.items():
        climatology[key] = {}
        for var, (s, s2, n) in var_map.items():
            if n > 1:
                mean = s / n
                var_val = (s2 / n) - (mean * mean)
                std = math.sqrt(max(var_val, 1e-4))
            else:
                mean = s if n == 1 else 25.0
                std = 5.0
            climatology[key][var] = (mean, std)

    verdicts = []
    for r in rows:
        st = r["station_id"]
        dt = _parse_dt(r["ts_utc"])
        key = (st, dt.month, dt.hour)
        clim = climatology.get(key, {"T": (25.0, 5.0), "RH": (60.0, 15.0), "P": (1013.0, 10.0)})

        var_results = {}
        has_anomaly = False

        for var in ("T", "RH", "P"):
            val = r.get(var)
            if val is not None and not math.isnan(val):
                mean, std = clim.get(var, (25.0, 5.0))
                z = abs(val - mean) / (std if std > 0 else 1.0)
                if z > z_threshold:
                    has_anomaly = True
                    var_results[var] = {"label": "anomaly", "root_cause": "out_of_range", "prob": float(min(1.0, z / 10.0))}
                else:
                    var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}
            else:
                var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}

        overall = "anomaly" if has_anomaly else "normal"
        verdict = _make_verdict_record(st, r["ts_utc"], overall, var_results, model_version="baseline_zscore")
        verdicts.append(verdict)

    if out_path:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")

    return verdicts


def _extract_features(rows: list[dict]) -> tuple[list[list[float]], list[dict]]:
    """Extract window features: T, Td, P, 1h and 3h changes."""
    by_station: dict[str, list[dict]] = {}
    for r in rows:
        by_station.setdefault(r["station_id"], []).append(r)

    feature_matrix = []
    ordered_rows = []

    for st, st_rows in by_station.items():
        st_sorted = sorted(st_rows, key=lambda r: r["ts_utc"])
        for i, r in enumerate(st_sorted):
            t_curr = r.get("T", 25.0)
            rh_curr = r.get("RH", 60.0)
            p_curr = r.get("P", 1013.0)
            # Estimate Td
            td_curr = t_curr - ((100.0 - rh_curr) / 5.0)

            # 1h change (approx 4 steps assuming 15m cadence, or find prev)
            prev1 = st_sorted[max(0, i - 4)]
            t_1h = t_curr - prev1.get("T", t_curr)
            rh_1h = rh_curr - prev1.get("RH", rh_curr)
            p_1h = p_curr - prev1.get("P", p_curr)

            # 3h change (approx 12 steps)
            prev3 = st_sorted[max(0, i - 12)]
            t_3h = t_curr - prev3.get("T", t_curr)
            rh_3h = rh_curr - prev3.get("RH", rh_curr)
            p_3h = p_curr - prev3.get("P", p_curr)

            feat_vec = [t_curr, td_curr, p_curr, t_1h, rh_1h, p_1h, t_3h, rh_3h, p_3h]
            feature_matrix.append(feat_vec)
            ordered_rows.append(r)

    return feature_matrix, ordered_rows


def isolation_forest_baseline(
    rows: list[dict],
    train_rows: list[dict] | None = None,
    out_path: str | Path | None = None,
) -> list[dict]:
    """Isolation Forest baseline detector using window features."""
    fit_rows = train_rows if train_rows is not None else rows
    train_feats, _ = _extract_features(fit_rows)
    test_feats, test_rows = _extract_features(rows)

    if HAS_SKLEARN and train_feats:
        X_train = np.array(train_feats, dtype=np.float32)
        X_test = np.array(test_feats, dtype=np.float32)
        model = IsolationForest(contamination=0.05, random_state=42)
        model.fit(X_train)
        preds = model.predict(X_test)  # -1 for anomaly, 1 for inlier
        scores = -model.decision_function(X_test)  # higher = more anomalous
    else:
        # Fallback simple threshold if sklearn missing
        preds = [1] * len(test_feats)
        scores = [0.0] * len(test_feats)

    verdicts = []
    for r, p, sc in zip(test_rows, preds, scores):
        is_anomaly = bool(p == -1)
        overall = "anomaly" if is_anomaly else "normal"
        var_results = {
            "T": {"label": overall, "root_cause": "unknown" if is_anomaly else None, "prob": float(sc)},
            "RH": {"label": "normal", "root_cause": None, "prob": 0.0},
            "P": {"label": "normal", "root_cause": None, "prob": 0.0},
        }
        verdict = _make_verdict_record(r["station_id"], r["ts_utc"], overall, var_results, model_version="baseline_iforest")
        verdicts.append(verdict)

    if out_path:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")

    return verdicts
