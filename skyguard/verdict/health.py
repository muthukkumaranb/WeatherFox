"""Per-station, per-variable health score from the flag rate.

The score starts at 1.0, drops 0.05 for every flagged reading and recovers 0.01 for every normal one.
It is a flag-rate indicator, not a physical sensor diagnostic. No time-to-maintenance is estimated
(ttm_days is always None) until a degradation model exists.
"""


class HealthTracker:
    def __init__(self):
        self.scores = {}
        
    def update_health(self, station_id: str, variable: str, label: str, residual: float) -> tuple[float, str, float]:
        k = (station_id, variable)
        if k not in self.scores:
            self.scores[k] = 1.0
            
        score = self.scores[k]
        
        if label != "normal":
            score = max(0.0, score - 0.05)
        else:
            score = min(1.0, score + 0.01)
            
        self.scores[k] = score
        
        trend = "stable"
        if score < 0.5:
            trend = "declining"
        elif score > 0.8:
            trend = "improving"
            
        ttm_days = None  # no degradation model yet; never report a made-up number

        return score, trend, ttm_days

_tracker = HealthTracker()

def update_health(station_id: str, variable: str, label: str, residual: float) -> tuple[float, str, float]:
    return _tracker.update_health(station_id, variable, label, residual)
