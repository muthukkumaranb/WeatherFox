import numpy as np
from pathlib import Path

_CONFIG_CACHE: dict = {}


def get_config():
    """Config is read once per file version (keyed on mtime) instead of on every p-value:
    re-parsing the TOML for each reading took ~30 % of scoring time."""
    import copy
    import tomllib
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        return {}
    cached = _CONFIG_CACHE.get("cfg")
    if cached is None or cached[0] != mtime:
        try:
            with open(config_path, "rb") as f:
                cached = (mtime, tomllib.load(f))
        except Exception:
            return {}
        _CONFIG_CACHE["cfg"] = cached
    return copy.deepcopy(cached[1])

class ConformalCalibrator:
    def __init__(self):
        self.cal_scores = {} # (var, cadence) -> array of scores
        
    def calibrate(self, val_scores_dict: dict):
        """val_scores_dict: (var, cadence) -> list of scores"""
        for k, v in val_scores_dict.items():
            self.cal_scores[k] = np.sort(np.array(v, dtype=float))
            
    def p_value(self, score: float, var: str, cadence: int) -> float:
        cal = self.cal_scores.get((var, cadence))
        if cal is None:
            cal = self.cal_scores.get((var, 60))
        if cal is None or len(cal) == 0:
            return 1.0 # fallback
        # count how many calibration scores are >= score
        # Since array is sorted, we can use searchsorted
        idx = np.searchsorted(cal, score, side='left')
        count_ge = len(cal) - idx
        p = (1.0 + count_ge) / (len(cal) + 1.0)
        return p
        
    def get_labels(self, score: float, var: str, cadence: int) -> tuple[str, float]:
        config = get_config().get("conformal", {})
        alpha_anomaly = config.get("alpha_anomaly", 0.001)
        alpha_uncertain = config.get("alpha_uncertain", 0.01)
        
        p = self.p_value(score, var, cadence)
        
        if p < alpha_anomaly:
            return "anomaly", p
        elif p < alpha_uncertain:
            return "uncertain", p
        return "normal", p
