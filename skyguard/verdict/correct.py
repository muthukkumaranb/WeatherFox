def correct(variable: str, forecast: float, neighbour_median: float, forecast_sigma: float, neighbour_count: int) -> tuple[float, float, str]:
    if forecast is None:
        return None, None, "none"
        
    if neighbour_median is not None and neighbour_count >= 2:
        val = 0.6 * forecast + 0.4 * neighbour_median
        method = "forecast+neighbour blend"
    else:
        val = forecast
        method = "forecast only"
        
    return val, forecast_sigma, method
