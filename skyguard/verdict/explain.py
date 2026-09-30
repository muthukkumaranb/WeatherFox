def shap_reasons(features: dict, label: str = "normal", real_resid: float = 0.0, sigma: float = 1.0, var: str = "unknown") -> list[dict]:
    # Mock TreeSHAP
    # Real implementation would call model.predict(X, pred_contrib=True)
    reasons = []
    if label == "normal":
        return reasons
        
    var_units = {"T": "°C", "RH": "%", "P": "hPa"}
    unit = var_units.get(var, "")
        
    for k, v in list(features.items())[:3]:
        if v is not None:
            if k == f"residual_{var}":
                direction = "above" if real_resid > 0 else "below"
                size = abs(real_resid) / sigma if sigma > 0 else 0
                text = f"{var} is {abs(real_resid):.1f} {unit} {direction} forecast ({size:.1f} σ)"
                reasons.append({
                    "feature": k,
                    "value": float(real_resid),
                    "contribution": 0.5,
                    "text": text.strip()
                })
            else:
                reasons.append({
                    "feature": k,
                    "value": float(v),
                    "contribution": 0.5,
                    "text": f"{k} is anomalous"
                })
    return reasons

def suggest_action(root_cause: str, severity: str) -> str:
    actions = {
        "spike": "Inspect sensor wiring; value excluded from products",
        "frozen": "Check sensor response; may need replacement",
        "drift": "Schedule calibration; apply correction",
        "offset": "Check calibration offset",
        "noise": "Inspect connection and shield",
        "out_of_range": "Sensor failure likely",
        "radiation": "Verify radiation shield",
        "power": "Check battery and solar panel",
        "comms_gap": "Check telemetry link",
        "duplicate": "Check ingest logic",
        "timeshift": "Sync datalogger clock",
        "unknown": "Manual review required"
    }
    return actions.get(root_cause, "No action required")
