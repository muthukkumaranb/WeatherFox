#ifndef SKYGUARD_THRESHOLDS_H
#define SKYGUARD_THRESHOLDS_H

// Generated from config/skyguard.toml

#define RG_T_MIN -40.0f
#define RG_T_MAX 60.0f
#define RG_RH_MIN 0.0f
#define RG_RH_MAX 103.0f
#define RG_P_MIN 600.0f
#define RG_P_MAX 1100.0f
#define RG_FROZEN_HOURS 6.0f
#define RG_FROZEN_HOURS_INTEGER 12.0f
#define RG_MIN_FROZEN_READINGS 3
#define RG_FOG_RH_THRESHOLD 97.0f
#define RG_FOG_TD_DIFF_MAX 0.5f
#define RG_TD_MAX_ABOVE_T 0.2f

typedef struct {
    float t_limit;
    float rh_limit;
    float p_limit;
} rg_step_limits_t;

static inline rg_step_limits_t rg_get_step_limits(int cadence_min) {
    if (cadence_min <= 1) return (rg_step_limits_t){ 3.0f, 10.0f, 0.5f };
    if (cadence_min <= 15) return (rg_step_limits_t){ 5.0f, 20.0f, 1.5f };
    if (cadence_min <= 30) return (rg_step_limits_t){ 6.0f, 25.0f, 2.0f };
    if (cadence_min <= 60) return (rg_step_limits_t){ 8.0f, 30.0f, 3.0f };
    return (rg_step_limits_t){ 12.0f, 40.0f, 6.0f };
}

#endif // SKYGUARD_THRESHOLDS_H
