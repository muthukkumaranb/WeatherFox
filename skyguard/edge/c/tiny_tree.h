#ifndef TINY_TREE_H
#define TINY_TREE_H

#ifdef __cplusplus
extern "C" {
#endif

// features array indices:
// 0: 1h_change
// 1: step_vs_previous
// 2: run_length
// 3: t_minus_td
// 4: 6h_var_ratio
int tree_predict(const float* features);

#ifdef __cplusplus
}
#endif

#endif // TINY_TREE_H
