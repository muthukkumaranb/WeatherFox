import numpy as np
import lightgbm as lgb
from skyguard.contract import assert_no_leak

class NeighbourModel:
    def __init__(self):
        self.models = {}
        self.feature_names = []
        
    def extract_features(self, target_anomaly: float, neighbour_anomalies: list[float], distances: list[float], source: str) -> dict:
        feats = {}
        feats["count"] = len(neighbour_anomalies)
        if not neighbour_anomalies:
            feats["median"] = None
            feats["mean"] = None
            feats["spread"] = None
        else:
            feats["median"] = np.median(neighbour_anomalies)
            if sum(distances) > 0:
                weights = [1.0 / (d + 1) for d in distances]
                feats["mean"] = np.average(neighbour_anomalies, weights=weights)
            else:
                feats["mean"] = np.mean(neighbour_anomalies)
            feats["spread"] = np.max(neighbour_anomalies) - np.min(neighbour_anomalies)
            
        feats["is_metar"] = 1 if "metar" in source else 0
        return feats

    def fit(self, train_data: dict):
        # train_data: var -> list of (target_anomaly, neighbour_anomalies, distances, source)
        for var, items in train_data.items():
            if not items:
                continue
            X_all = []
            y_all = []
            for t_anom, n_anoms, dists, source in items:
                feats = self.extract_features(t_anom, n_anoms, dists, source)
                X_all.append(feats)
                y_all.append(t_anom)
                
            if not X_all:
                continue
                
            self.feature_names = sorted(list(X_all[0].keys()))
            assert_no_leak(self.feature_names)
            
            X_mat = []
            for x in X_all:
                X_mat.append([x.get(k) for k in self.feature_names])
            X_mat = np.array(X_mat, dtype=float)
            y = np.array(y_all, dtype=float)
            
            mask = ~np.isnan(y)
            X_train = X_mat[mask]
            y_train = y[mask]
            
            model = lgb.LGBMRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, n_jobs=-1, random_state=42)
            model.fit(X_train, y_train)
            self.models[var] = model

    def predict(self, neighbour_anomalies: list[float], distances: list[float], source: str, var: str) -> float:
        if var not in self.models or not neighbour_anomalies:
            return None
        feats = self.extract_features(0.0, neighbour_anomalies, distances, source)
        x = np.array([[feats.get(k) for k in self.feature_names]], dtype=float)
        return self.models[var].predict(x)[0]
