import tomllib
from pathlib import Path

_config = None
def _get_config():
    global _config
    if _config is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
        with open(config_path, "rb") as f:
            _config = tomllib.load(f)["rule_gate"]
    return _config

def correct(variable: str, forecast: float, neighbour_median: float, forecast_sigma: float, neighbour_count: int) -> tuple[float, float, str]:
    if forecast is None:
        return None, None, "none"
        
    if neighbour_median is not None and neighbour_count >= 2:
        val = 0.6 * forecast + 0.4 * neighbour_median
        method = "forecast+neighbour blend"
    else:
        val = forecast
        method = "forecast only"
        
    config = _get_config()
    min_val = config.get(f"{variable}_min", -float('inf'))
    max_val = config.get(f"{variable}_max", float('inf'))
    if variable == "RH":
        max_val = min(max_val, 100.0)
    val = max(min_val, min(val, max_val))
        
    return val, forecast_sigma, method
