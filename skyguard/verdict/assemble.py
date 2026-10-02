from skyguard.contract import worst_label, validate_verdict

def assemble_verdict(r: dict, var_results: dict, *, model_version: str = "1.0.0") -> dict:
    labels = [res["label"] for res in var_results.values() if "label" in res]
    overall = worst_label(labels) if labels else "normal"
    
    spatials = [res["spatial_support"] for res in var_results.values() if "spatial_support" in res]
    overall_spatial = "neighbours_normal"
    
    if "no_model" in spatials:
        overall_spatial = "no_model"
    elif "no_neighbours" in spatials:
        overall_spatial = "no_neighbours"
        
    gen = False
    if overall == "normal":
        if "neighbours_also_deviating" in spatials:
            gen = True
            overall_spatial = "neighbours_also_deviating"
            
    verdict = {
        "schema_v": "1.0",
        "station_id": r["station_id"],
        "ts_utc": r["ts_utc"],
        "label": overall,
        "phase": "final",
        "genuine_event": gen,
        "model_version": model_version,
        "spatial_support": overall_spatial,
        "n_neighbours": 0 if overall_spatial in ("no_neighbours", "no_model") else 5,
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
        if "imd_flag" in res:
            v_dict["imd_flag"] = res["imd_flag"]
        if "corrected_supplied" in res:
            v_dict["corrected_supplied"] = res["corrected_supplied"]
            
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
