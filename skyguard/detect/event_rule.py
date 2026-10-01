def evaluate_event_rule(target_val: float, target_pred: float, target_3h_change: float,
                        neighbour_3h_changes: list[float], neighbour_resids: list[float],
                        metar_rounding_tolerance_C: float = 1.0, is_metar: bool = False) -> str:
    if len(neighbour_3h_changes) < 2:
        return "no_neighbours"
        
    # check co-move
    target_sign = 1 if target_3h_change > 0 else -1
    co_move_count = sum(1 for c in neighbour_3h_changes if (1 if c > 0 else -1) == target_sign)
    co_move = co_move_count / len(neighbour_3h_changes)
    
    # check if neighbour anomaly is small
    # median neighbour anomaly
    # median neighbour residual
    import numpy as np
    med_n_resid = np.median(neighbour_resids)
    
    threshold = metar_rounding_tolerance_C if is_metar else 0.5
    
    if co_move >= 0.6 and abs(med_n_resid) > threshold:
        return "neighbours_also_deviating"
        
    return "neighbours_normal"
