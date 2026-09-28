import math
import numpy as np
from datetime import datetime
import lightgbm as lgb
from skyguard.contract import assert_no_leak

class Forecaster:
    def __init__(self):
        self.models = {}
        self.feature_names = []
        self.q05_models = {}
        self.q95_models = {}
        
    def extract_features(self, r: dict, history: list[dict], climatology) -> dict:
        feats = {}
        
        # history is oldest to newest, excluding current row r
        # lags: 1,2,3,6,12,24 h. Assume history has `ts_utc`
        dt = datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        feats["hour_sin"] = math.sin(2 * math.pi * dt.hour / 24)
        feats["hour_cos"] = math.cos(2 * math.pi * dt.hour / 24)
        doy = dt.timetuple().tm_yday
        feats["doy_sin"] = math.sin(2 * math.pi * doy / 365)
        feats["doy_cos"] = math.cos(2 * math.pi * doy / 365)
        
        # Climatology
        for var in ("T", "Td", "P"):
            clim = climatology.get(r["station_id"], dt.month, dt.hour, var)
            feats[f"clim_{var}_median"] = clim["median"]
            feats[f"clim_{var}_mad"] = clim["mad"]
            
        # Lags
        lags_h = [1, 2, 3, 6, 12, 24]
        # find closest row in history for each lag
        for lh in lags_h:
            target_ts = dt.timestamp() - lh * 3600
            best_diff = float('inf')
            best_r = None
            for hr in history:
                hts = datetime.strptime(hr["ts_utc"], "%Y-%m-%dT%H:%M:%SZ").timestamp()
                diff = abs(hts - target_ts)
                if diff < best_diff and diff <= 1800: # within 30 min
                    best_diff = diff
                    best_r = hr
                    
            for var in ("T", "Td", "P"):
                feats[f"{var}_lag_{lh}h"] = best_r.get(var) if best_r else None
                
        feats["cadence_min"] = r.get("cadence_min", 60)
        return feats

    def fit(self, train_rows: list[dict], climatology):
        # build history per station
        by_station = {}
        for r in train_rows:
            by_station.setdefault(r["station_id"], []).append(r)
            
        X_all = []
        Y_all = {"T": [], "Td": [], "P": []}
        
        for sid, s_rows in by_station.items():
            s_rows.sort(key=lambda x: x["ts_utc"])
            history = []
            for r in s_rows:
                # build features
                feats = self.extract_features(r, history, climatology)
                # target
                for var in ("T", "Td", "P"):
                    Y_all[var].append(r.get(var))
                X_all.append(feats)
                history.append(r)
                
        if not X_all:
            return
            
        self.feature_names = sorted(list(X_all[0].keys()))
        assert_no_leak(self.feature_names)
        
        X_mat = []
        for x in X_all:
            X_mat.append([x.get(k) for k in self.feature_names])
        X_mat = np.array(X_mat, dtype=float)
        
        for var in ("T", "Td", "P"):
            y = np.array(Y_all[var], dtype=float)
            mask = ~np.isnan(y)
            if not np.any(mask):
                continue
                
            X_train = X_mat[mask]
            y_train = y[mask]
            
            model = lgb.LGBMRegressor(n_estimators=100, max_depth=5, learning_rate=0.1, n_jobs=-1, random_state=42)
            model.fit(X_train, y_train)
            self.models[var] = model
            
            # quantiles
            q05 = lgb.LGBMRegressor(objective='quantile', alpha=0.05, n_estimators=100, max_depth=5, learning_rate=0.1, n_jobs=-1, random_state=42)
            q05.fit(X_train, y_train)
            self.q05_models[var] = q05
            
            q95 = lgb.LGBMRegressor(objective='quantile', alpha=0.95, n_estimators=100, max_depth=5, learning_rate=0.1, n_jobs=-1, random_state=42)
            q95.fit(X_train, y_train)
            self.q95_models[var] = q95

    def predict(self, r: dict, history: list[dict], climatology) -> dict:
        feats = self.extract_features(r, history, climatology)
        x = np.array([[feats.get(k) for k in self.feature_names]], dtype=float)
        
        res = {}
        for var, model in self.models.items():
            pred = model.predict(x)[0]
            q05 = self.q05_models[var].predict(x)[0]
            q95 = self.q95_models[var].predict(x)[0]
            res[var] = {"pred": pred, "q05": q05, "q95": q95}
        return res
