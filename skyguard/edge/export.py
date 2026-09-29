import sys
import numpy as np
from pathlib import Path
from sklearn.tree import DecisionTreeClassifier

def export_to_c(tree, feature_names, out_h, out_c):
    n_nodes = tree.tree_.node_count
    children_left = tree.tree_.children_left
    children_right = tree.tree_.children_right
    feature = tree.tree_.feature
    threshold = tree.tree_.threshold
    value = tree.tree_.value

    def recurse(node, depth):
        indent = "    " * depth
        if children_left[node] != children_right[node]:
            f_idx = feature[node]
            thr = threshold[node]
            s = f"{indent}if (features[{f_idx}] <= {thr}f) {{\n"
            s += recurse(children_left[node], depth + 1)
            s += f"{indent}}} else {{\n"
            s += recurse(children_right[node], depth + 1)
            s += f"{indent}}}\n"
            return s
        else:
            class_val = np.argmax(value[node][0])
            return f"{indent}return {class_val};\n"

    code_body = recurse(0, 1)

    h_code = """#ifndef TINY_TREE_H
#define TINY_TREE_H

#ifdef __cplusplus
extern "C" {
#endif

int tree_predict(const float* features);

#ifdef __cplusplus
}
#endif

#endif // TINY_TREE_H
"""
    c_code = f"""#include "tiny_tree.h"

int tree_predict(const float* features) {{
{code_body}}}
"""
    out_h.parent.mkdir(parents=True, exist_ok=True)
    with open(out_h, "w") as f:
        f.write(h_code)
    with open(out_c, "w") as f:
        f.write(c_code)

def main():
    root = Path(__file__).resolve().parent.parent.parent
    try:
        from skyguard.data.inject import synthetic_data
        X, y = synthetic_data()
        data_src = "synthetic"
    except ImportError:
        # Fallback to simple random if inject isn't implemented by Person A yet
        np.random.seed(42)
        X = np.random.randn(5000, 5)
        y = np.zeros(5000, dtype=int)
        y[(np.abs(X[:, 1]) > 3) | (X[:, 2] > 5)] = 1
        data_src = "synthetic (fallback)"
    
    clf = DecisionTreeClassifier(max_depth=6, random_state=42)
    clf.fit(X, y)
    
    out_h = root / "skyguard" / "edge" / "c" / "tiny_tree.h"
    out_c = root / "skyguard" / "edge" / "c" / "tiny_tree.c"
    
    fnames = ["step", "1h_change", "run_length", "td_minus_t", "var_ratio"]
    export_to_c(clf, fnames, out_h, out_c)
    print(f"Exported tiny_tree.c from {data_src} data.")

if __name__ == "__main__":
    main()
