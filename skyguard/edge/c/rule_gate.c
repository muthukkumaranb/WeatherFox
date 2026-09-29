#include "rule_gate.h"
#include "thresholds.h"
#include <math.h>

#ifndef NULL
#define NULL 0
#endif

static bool is_fog_condition(const rg_row_t* newest) {
    if (newest->has_RH && newest->RH >= RG_FOG_RH_THRESHOLD) {
        if (newest->has_T && newest->has_Td && (newest->T - newest->Td) <= RG_FOG_TD_DIFF_MAX) {
            return true;
        }
    }
    return false;
}

// Helper to check frozen condition
static bool check_frozen(const rg_row_t* rows, int rows_count, int req_hours, float newest_val, char var_type) {
    long long dt_newest = rows[rows_count - 1].ts_utc;
    int count = 0;
    long long oldest_dt = dt_newest;
    bool same_val = true;

    for (int i = rows_count - 1; i >= 0; i--) {
        long long dt = rows[i].ts_utc;
        if ((dt_newest - dt) <= (req_hours * 3600 + 60)) {
            bool has_var = false;
            float val = 0;
            if (var_type == 'T' && rows[i].has_T) { has_var = true; val = rows[i].T; }
            else if (var_type == 'R' && rows[i].has_RH) { has_var = true; val = rows[i].RH; }
            else if (var_type == 'P' && rows[i].has_P) { has_var = true; val = rows[i].P; }

            if (has_var) {
                count++;
                oldest_dt = dt;
                if (val != newest_val) {
                    same_val = false;
                    break;
                }
            }
        } else {
            break; // rows are ordered, newest at the end
        }
    }

    if (same_val && count >= RG_MIN_FROZEN_READINGS) {
        float span_hours = (dt_newest - oldest_dt) / 3600.0f;
        if (span_hours >= (req_hours - 0.05f)) {
            return true; // SUSPECT
        }
    }
    return false;
}

rg_result_t rg_check(const rg_row_t* rows, int rows_count) {
    rg_result_t res = {RG_OK, RG_OK, RG_OK};
    
    if (rows_count == 0) return res;
    
    const rg_row_t* newest = &rows[rows_count - 1];
    bool is_fog = is_fog_condition(newest);
    rg_step_limits_t step_limits = rg_get_step_limits(newest->cadence_min);
    
    // T Check
    if (newest->has_T) {
        if (newest->T < RG_T_MIN || newest->T > RG_T_MAX) {
            res.status_T = RG_FAIL;
        } else {
            if (rows_count > 1 && rows[rows_count - 2].has_T) {
                float prev_t = rows[rows_count - 2].T;
                float diff = fabsf(newest->T - prev_t);
                if (diff > step_limits.t_limit) {
                    res.status_T = RG_SUSPECT;
                }
            }
            if (res.status_T == RG_OK && !is_fog) {
                int req_hours = newest->is_metar_speci ? (int)RG_FROZEN_HOURS_INTEGER : (int)RG_FROZEN_HOURS;
                if (!newest->is_metar_speci) {
                    // Check if all T values in the window are integers
                    bool all_int = true;
                    long long dt_newest = newest->ts_utc;
                    bool has_any = false;
                    for (int i = rows_count - 1; i >= 0; i--) {
                        if ((dt_newest - rows[i].ts_utc) <= (req_hours * 3600 + 60)) {
                            if (rows[i].has_T) {
                                has_any = true;
                                if (rows[i].T != (float)(int)rows[i].T) {
                                    all_int = false;
                                    break;
                                }
                            }
                        } else {
                            break;
                        }
                    }
                    if (has_any && all_int) {
                        req_hours = (int)RG_FROZEN_HOURS_INTEGER;
                    }
                }
                
                if (check_frozen(rows, rows_count, req_hours, newest->T, 'T')) {
                    res.status_T = RG_SUSPECT;
                }
            }
        }
    }
    
    // RH Check
    if (newest->has_RH) {
        if (newest->RH < RG_RH_MIN || newest->RH > RG_RH_MAX) {
            res.status_RH = RG_FAIL;
        } else {
            if (newest->has_T && newest->has_Td) {
                float max_td = newest->T + RG_TD_MAX_ABOVE_T;
                if (newest->Td > max_td) {
                    res.status_RH = RG_FAIL;
                }
            }
            
            if (res.status_RH == RG_OK && rows_count > 1 && rows[rows_count - 2].has_RH) {
                float prev_rh = rows[rows_count - 2].RH;
                float diff = fabsf(newest->RH - prev_rh);
                if (diff > step_limits.rh_limit) {
                    res.status_RH = RG_SUSPECT;
                }
            }
            
            if (res.status_RH == RG_OK && !is_fog) {
                int req_hours = newest->is_metar_speci ? (int)RG_FROZEN_HOURS_INTEGER : (int)RG_FROZEN_HOURS;
                if (!newest->is_metar_speci) {
                    bool all_int = true;
                    long long dt_newest = newest->ts_utc;
                    bool has_any = false;
                    for (int i = rows_count - 1; i >= 0; i--) {
                        if ((dt_newest - rows[i].ts_utc) <= (req_hours * 3600 + 60)) {
                            if (rows[i].has_RH) {
                                has_any = true;
                                if (rows[i].RH != (float)(int)rows[i].RH) {
                                    all_int = false;
                                    break;
                                }
                            }
                        } else {
                            break;
                        }
                    }
                    if (has_any && all_int) {
                        req_hours = (int)RG_FROZEN_HOURS_INTEGER;
                    }
                }
                
                if (check_frozen(rows, rows_count, req_hours, newest->RH, 'R')) {
                    res.status_RH = RG_SUSPECT;
                }
            }
        }
    }
    
    // P Check
    if (newest->has_P) {
        if (newest->P < RG_P_MIN || newest->P > RG_P_MAX) {
            res.status_P = RG_FAIL;
        } else {
            if (rows_count > 1 && rows[rows_count - 2].has_P) {
                float prev_p = rows[rows_count - 2].P;
                float diff = fabsf(newest->P - prev_p);
                if (diff > step_limits.p_limit) {
                    res.status_P = RG_SUSPECT;
                }
            }
            
            if (res.status_P == RG_OK) {
                int req_hours = newest->is_metar_speci ? (int)RG_FROZEN_HOURS_INTEGER : (int)RG_FROZEN_HOURS;
                if (!newest->is_metar_speci) {
                    bool all_int = true;
                    long long dt_newest = newest->ts_utc;
                    bool has_any = false;
                    for (int i = rows_count - 1; i >= 0; i--) {
                        if ((dt_newest - rows[i].ts_utc) <= (req_hours * 3600 + 60)) {
                            if (rows[i].has_P) {
                                has_any = true;
                                if (rows[i].P != (float)(int)rows[i].P) {
                                    all_int = false;
                                    break;
                                }
                            }
                        } else {
                            break;
                        }
                    }
                    if (has_any && all_int) {
                        req_hours = (int)RG_FROZEN_HOURS_INTEGER;
                    }
                }
                
                if (check_frozen(rows, rows_count, req_hours, newest->P, 'P')) {
                    res.status_P = RG_SUSPECT;
                }
            }
        }
    }
    
    return res;
}
