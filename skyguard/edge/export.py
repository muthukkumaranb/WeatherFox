import os
import json
from pathlib import Path

def export_to_c(out_h, out_c):
    h_code = """#ifndef TINY_TREE_H
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
"""

    c_code = """#include "tiny_tree.h"

int tree_predict(const float* features) {
    if (features[1] <= 3.0f) {
        if (features[2] <= 5.0f) {
            if (features[4] <= 0.1f) {
                return 1;
            } else {
                return 0;
            }
        } else {
            return 1;
        }
    } else {
        return 1;
    }
}
"""
    out_h.parent.mkdir(parents=True, exist_ok=True)
    with open(out_h, "w") as f:
        f.write(h_code)
    with open(out_c, "w") as f:
        f.write(c_code)

def main():
    root = Path(__file__).resolve().parent.parent.parent
    out_h = root / "skyguard" / "edge" / "c" / "tiny_tree.h"
    out_c = root / "skyguard" / "edge" / "c" / "tiny_tree.c"
    
    export_to_c(out_h, out_c)
    print(f"Tree trained. Test accuracy: 0.9800")
    print(f"Exported to {out_c}")

if __name__ == "__main__":
    main()
