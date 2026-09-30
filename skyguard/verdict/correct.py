import tomllib
import os

_config = None
_limits = {}

def _get_limits():
    global _config, _limits
    if _config is None:
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "skyguard.toml")
            with open(config_path, "rb") as f:
                _config = tomllib.load(f)
            rg = _config.get("rule_gate", {})
            _limits["T_min"] = rg.get("T_min", -40.0)
            _limits["T_max"] = rg.get("T_max", 55.0)
            _limits["RH_min"] = rg.get("RH_min", 0.0)
            _limits["RH_max"] = 100.0  # as requested, clipped to 100
            _limits["P_min"] = rg.get("P_min", 850.0)
            _limits["P_max"] = rg.get("P_max", 1085.0)
        except Exception:
            _limits = {
                "T_min": -40.0, "T_max": 55.0,
                "RH_min": 0.0, "RH_max": 100.0,
                "P_min": 850.0, "P_max": 1085.0
            }
    return _limits

def correct(variable: str, forecast: float, neighbour_median: float, forecast_sigma: float, neighbour_count: int) -> tuple[float, float, str]:
    if forecast is None:
        return None, None, "none"
        
    if neighbour_median is not None and neighbour_count >= 2:
        val = 0.6 * forecast + 0.4 * neighbour_median
        method = "forecast+neighbour blend"
    else:
        val = forecast
        method = "forecast only"
        
    limits = _get_limits()
    if variable == "T":
        val = max(limits["T_min"], min(val, limits["T_max"]))
    elif variable == "RH":
        val = max(limits["RH_min"], min(val, limits["RH_max"]))
    elif variable == "P":
        val = max(limits["P_min"], min(val, limits["P_max"]))
        
    return val, forecast_sigma, method
