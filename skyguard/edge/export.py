"""Export sklearn DecisionTreeClassifier as C code.  Owner: Person C.

Trains a DecisionTreeClassifier (max_depth<=6) on synthetic anomaly data
and generates skyguard/edge/c/tiny_tree.c from the fitted tree.

No hand-written tree — all thresholds come from sklearn's fit.
"""
import sys
from pathlib import Path


def export_to_c(tree, feature_names, out_h, out_c):
    """Convert a fitted sklearn tree to C source files."""
    import numpy as np

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
    """Train sklearn tree and generate tiny_tree.c.  sklearn imported lazily."""
    # Lazy import — sklearn DLLs may be blocked on managed Windows
    try:
        import numpy as np
        from sklearn.tree import DecisionTreeClassifier
    except ImportError as e:
        print(f"sklearn/numpy not available: {e}")
        print("Cannot generate tiny_tree.c — install sklearn on a Linux machine.")
        sys.exit(1)

    root = Path(__file__).resolve().parent.parent.parent

    try:
        from skyguard.data.inject import synthetic_data
        X, y = synthetic_data()
        data_src = "synthetic (skyguard.data.inject)"
    except (ImportError, Exception):
        # Fallback to simple random data if inject isn't available
        np.random.seed(42)
        n = 5000
        X = np.random.randn(n, 5)
        y = np.zeros(n, dtype=int)
        # Create anomaly pattern: T deviation > 3σ or large positive step
        y[(np.abs(X[:, 1]) > 3) | (X[:, 2] > 5)] = 1
        data_src = "synthetic (fallback random)"

    clf = DecisionTreeClassifier(max_depth=6, random_state=42)
    clf.fit(X, y)

    out_h = root / "skyguard" / "edge" / "c" / "tiny_tree.h"
    out_c = root / "skyguard" / "edge" / "c" / "tiny_tree.c"

    fnames = ["step", "1h_change", "run_length", "td_minus_t", "var_ratio"]
    export_to_c(clf, fnames, out_h, out_c)
    print(f"Exported tiny_tree.c from {data_src} data.")
    print(f"  tree_predict uses {clf.tree_.node_count} nodes, max_depth={clf.get_depth()}")
    print(f"  Written to: {out_c}")


if __name__ == "__main__":
    main()
