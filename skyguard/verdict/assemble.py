from skyguard.contract import worst_label, validate_verdict

def assemble_verdict(r: dict, var_results: dict) -> dict:
    labels = [res["label"] for res in var_results.values() if "label" in res]
    overall = worst_label(labels) if labels else "normal"
    
    # genuine_event = True only when label == "normal" AND spatial_support == "neighbours_also_deviating"
    gen = False
    overall_spatial = "neighbours_normal"
    if overall == "normal":
        spatials = [res["spatial_support"] for res in var_results.values() if "spatial_support" in res]
        if "neighbours_also_deviating" in spatials:
            gen = True
            overall_spatial = "neighbours_also_deviating"
        elif "no_neighbours" in spatials:
            overall_spatial = "no_neighbours"
            
    verdict = {
        "schema_v": "1.0",
        "station_id": r["station_id"],
        "ts_utc": r["ts_utc"],
        "label": overall,
        "phase": "final",
        "genuine_event": gen,
        "model_version": "1.0.0",
        "spatial_support": overall_spatial,
        "n_neighbours": 0 if overall_spatial == "no_neighbours" else 5,
        "vars": {}
    }
    
    for var, res in var_results.items():
        v_dict = {
            "label": res["label"],
            "root_cause": res.get("root_cause") or "unknown",
            "confidence": res.get("confidence", 0.0),
            "severity": res.get("severity", "low"),
            "reasons": res.get("reasons", []),
            "action": res.get("action", "None")
        }
        if "corrected" in res:
            v_dict["corrected"] = res["corrected"]
            
        verdict["vars"][var] = v_dict
        
        if "health" in res:
            if "health" not in verdict:
                verdict["health"] = {}
            verdict["health"][var] = res["health"]
        
    try:
        validate_verdict(verdict)
    except Exception as e:
        # fallback for debug
        raise e
    return verdict
