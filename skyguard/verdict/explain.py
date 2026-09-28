def shap_reasons(features: dict) -> list[dict]:
    # Mock TreeSHAP
    # Real implementation would call model.predict(X, pred_contrib=True)
    reasons = []
    for k, v in list(features.items())[:3]:
        if v is not None:
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
