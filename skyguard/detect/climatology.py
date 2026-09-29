import numpy as np
from collections import defaultdict
from datetime import datetime

class Climatology:
    def __init__(self):
        # station_id -> var -> (month, hour) -> {'median': val, 'mad': val}
        self.stats = {}
        
    def fit(self, train_rows: list[dict]):
        # Group values
        grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for r in train_rows:
            sid = r["station_id"]
            dt = datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
            mo, hr = dt.month, dt.hour
            for var in ("T", "Td", "P"):
                val = r.get(var)
                if val is not None:
                    grouped[sid][var][(mo, hr)].append(val)
                    
        for sid, var_dict in grouped.items():
            for var, time_dict in var_dict.items():
                for (mo, hr), vals in time_dict.items():
                    if len(vals) > 0:
                        med = np.median(vals)
                        mad = np.median(np.abs(vals - med))
                        self.stats.setdefault(sid, {}).setdefault(var, {})[(mo, hr)] = {"median": float(med), "mad": float(mad)}
                        
    def get(self, station_id: str, month: int, hour: int, var: str) -> dict:
        return self.stats.get(station_id, {}).get(var, {}).get((month, hour), {"median": None, "mad": None})
