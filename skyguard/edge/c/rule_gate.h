#ifndef RULE_GATE_H
#define RULE_GATE_H

#include <stdbool.h>

#define RG_OK 0
#define RG_SUSPECT 1
#define RG_FAIL 2

typedef struct {
    float T;
    float Td;
    float RH;
    float P;
    
    bool has_T;
    bool has_Td;
    bool has_RH;
    bool has_P;
    
    int cadence_min;
    bool is_metar_speci;
    
    // Unix timestamp
    long long ts_utc;
} rg_row_t;

typedef struct {
    int status_T; // RG_OK, RG_SUSPECT, RG_FAIL
    int status_RH;
    int status_P;
} rg_result_t;

#ifdef __cplusplus
extern "C" {
#endif

// Check a single new row against an array of historical rows (newest at the end).
// rows_count does NOT include the new row. The new row is evaluated.
// Note: Python rule_gate `check(rows)` takes a list of rows including the newest one at the end.
// For C, we can just pass all rows, and `rows[rows_count - 1]` is the newest.
rg_result_t rg_check(const rg_row_t* rows, int rows_count);

#ifdef __cplusplus
}
#endif

#endif // RULE_GATE_H
