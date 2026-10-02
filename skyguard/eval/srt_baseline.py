"""IMD spatial regression test baseline (srt_baseline.py)."""

import json
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from skyguard.data.registry import load_registry, neighbours
from skyguard.eval.baselines import _parse_dt, _make_verdict_record

def fit_spatial_models(train_rows: list[dict], registry: dict) -> dict:
    """Fit linear regression models for each station using up to 3 neighbours."""
    # Group data by station
    df = pd.DataFrame(train_rows)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    
    models = {}
    
    # We pivot to have ts_utc as index and station_ids as columns
    for var in ("T", "RH", "P"):
        var_df = df[["ts_utc", "station_id", var]].dropna()
        pivoted = var_df.pivot(index="ts_utc", columns="station_id", values=var)
        
        for sid in pivoted.columns:
            if sid not in models:
                models[sid] = {"T": [], "RH": [], "P": []}
                
            nbs = neighbours(sid, registry, max_km=200.0)
            valid_nbs = []
            
            y = pivoted[sid]
            for nb in nbs:
                if nb in pivoted.columns:
                    x = pivoted[nb]
                    # align
                    mask = ~(y.isna() | x.isna())
                    if mask.sum() < 30: # minimum points
                        continue
                        
                    y_sub = y[mask]
                    x_sub = x[mask]
                    
                    # Compute R^2
                    correlation = np.corrcoef(x_sub, y_sub)[0, 1]
                    r2 = correlation ** 2
                    
                    if r2 > 0.5:
                        # Linear regression: y = m*x + c
                        m, c = np.polyfit(x_sub, y_sub, 1)
                        # variance of residuals
                        residuals = y_sub - (m * x_sub + c)
                        sigma = np.std(residuals)
                        
                        valid_nbs.append({
                            "nb_id": nb,
                            "r2": r2,
                            "m": m,
                            "c": c,
                            "sigma": sigma
                        })
            
            # sort by r2 descending, keep up to 3
            valid_nbs.sort(key=lambda x: x["r2"], reverse=True)
            models[sid][var] = valid_nbs[:3]
            
    return models

def srt_baseline(rows: list[dict], train_rows: list[dict], out_path: str | Path | None = None) -> list[dict]:
    registry = load_registry(str(Path("data/station_registry.csv")))
    models = fit_spatial_models(train_rows, registry)
    
    # Group test rows by time
    df_test = pd.DataFrame(rows)
    df_test["ts_utc_dt"] = pd.to_datetime(df_test["ts_utc"])
    
    verdicts = []
    
    # We pivot test data just like train data to easily look up neighbours' values
    for var in ("T", "RH", "P"):
        df_test[f"_{var}"] = df_test[var]
    
    # to fast lookup neighbor values:
    time_indexed = df_test.set_index(["ts_utc_dt", "station_id"])
    
    for i, r in df_test.iterrows():
        sid = r["station_id"]
        ts_dt = r["ts_utc_dt"]
        ts_str = r["ts_utc"]
        
        var_results = {}
        has_anomaly = False
        
        for var in ("T", "RH", "P"):
            obs = r[var]
            if pd.isna(obs):
                var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}
                continue
                
            model_info = models.get(sid, {}).get(var, [])
            estimates = []
            sigmas = []
            
            for nb_info in model_info:
                nb_id = nb_info["nb_id"]
                try:
                    nb_val = time_indexed.at[(ts_dt, nb_id), f"_{var}"]
                    if not pd.isna(nb_val):
                        # estimate = m * x + c
                        est = nb_info["m"] * nb_val + nb_info["c"]
                        estimates.append(est)
                        sigmas.append(nb_info["sigma"])
                except KeyError:
                    pass
            
            if len(estimates) >= 2:
                # weighted estimate (we can just use mean, or inverse variance)
                # "weighted estimate" - usually weighted by R^2 or inverse sigma
                # For simplicity, we use inverse sigma squared
                weights = [1.0 / (s**2 + 1e-6) for s in sigmas]
                weighted_est = np.average(estimates, weights=weights)
                
                # combined sigma
                combined_sigma = np.sqrt(1.0 / sum(weights))
                
                if abs(obs - weighted_est) > 3 * combined_sigma:
                    has_anomaly = True
                    var_results[var] = {"label": "anomaly", "root_cause": "spatial_anomaly", "prob": 0.99}
                else:
                    var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}
            else:
                var_results[var] = {"label": "normal", "root_cause": None, "prob": 0.0}
                
        overall = "anomaly" if has_anomaly else "normal"
        verdict = _make_verdict_record(sid, ts_str, overall, var_results, model_version="baseline_srt")
        verdicts.append(verdict)
        
    if out_path:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")
                
    return verdicts
