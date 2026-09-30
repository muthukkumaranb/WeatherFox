"""Export sklearn DecisionTreeClassifier as C code.  Owner: Person C.

Trains a DecisionTreeClassifier (max_depth<=6) on realistic weather fault data
(synthetic clean rows + injected spike, frozen, drift, and dewpoint faults)
and generates skyguard/edge/c/tiny_tree.c from the fitted tree.

No hand-written tree — all thresholds come from sklearn's fit.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path


def generate_fault_dataset(n_samples: int = 10000, seed: int = 42) -> tuple:
    """Generate synthetic weather rows with injected spike, frozen, drift, and dewpoint faults.

    Features per row (5 features matching edge harness):
      0: step (T_i - T_{i-1})
      1: 1h_change (T_i - T_{i-1})
      2: run_length (consecutive identical T readings)
      3: td_minus_t (Td_i - T_i)
      4: var_ratio (1.0 default)

    Labels:
      0: normal
      1: anomaly (fault)
    """
    import numpy as np

    rng = random.Random(seed)
    np_rng = np.random.RandomState(seed)

    features = []
    labels = []

    base_t = 25.0
    curr_t = base_t
    run_len = 1.0

    for i in range(n_samples):
        fault_type = None
        if i > 5 and rng.random() < 0.15:
            fault_type = rng.choice(["spike", "frozen", "drift", "dewpoint"])

        if fault_type == "spike":
            spike_val = rng.choice([8.0, 12.0, -8.0, -12.0]) + rng.uniform(-1.0, 1.0)
            next_t = curr_t + spike_val
            label = 1
        elif fault_type == "frozen":
            next_t = curr_t
            run_len += 1.0
            label = 1 if run_len >= 3 else 0
        elif fault_type == "drift":
            drift_val = rng.uniform(3.5, 7.0)
            next_t = curr_t + drift_val
            label = 1
        else:
            next_t = base_t + float(np_rng.normal(0, 1.5))
            if round(next_t, 2) == round(curr_t, 2):
                run_len += 1.0
            else:
                run_len = 1.0
            label = 0

        step = round(next_t - curr_t, 2)
        curr_t = next_t
        curr_rh = max(10.0, min(100.0, 50.0 + float(np_rng.normal(0, 5.0))))
        curr_td = curr_t - ((100.0 - curr_rh) / 5.0)

        if fault_type == "dewpoint":
            curr_td = curr_t + rng.uniform(1.5, 4.0)
            label = 1

        td_minus_t = round(curr_td - curr_t, 2)
        var_ratio = 1.0

        features.append([step, step, run_len, td_minus_t, var_ratio])
        labels.append(label)

    X = np.array(features, dtype=float)
    y = np.array(labels, dtype=int)
    return X, y


def export_to_c(tree, feature_names: list[str], out_h: Path, out_c: Path) -> None:
    """Convert a fitted sklearn tree to C source files."""
    import numpy as np

    children_left = tree.tree_.children_left
    children_right = tree.tree_.children_right
    feature = tree.tree_.feature
    threshold = tree.tree_.threshold
    value = tree.tree_.value

    def recurse(node: int, depth: int) -> str:
        indent = "    " * depth
        if children_left[node] != children_right[node]:
            f_idx = feature[node]
            thr = threshold[node]
            s = f"{indent}if (features[{f_idx}] <= {thr:.16f}f) {{\n"
            s += recurse(children_left[node], depth + 1)
            s += f"{indent}}} else {{\n"
            s += recurse(children_right[node], depth + 1)
            s += f"{indent}}}\n"
            return s
        else:
            class_val = int(np.argmax(value[node][0]))
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
    """Train sklearn tree and generate tiny_tree.c. Must FAIL loudly if sklearn is absent or dataset fails."""
    try:
        from sklearn.tree import DecisionTreeClassifier
        from sklearn.model_selection import train_test_split
    except ImportError as e:
        print(f"ERROR: sklearn/numpy not available: {e}", file=sys.stderr)
        print("Cannot train tiny_tree — install dependencies in .venv first.", file=sys.stderr)
        sys.exit(1)

    root = Path(__file__).resolve().parent.parent.parent

    training_data_desc = "synthetic clean rows + injected spike/frozen/drift/dewpoint faults"

    try:
        X, y = generate_fault_dataset(n_samples=10000, seed=42)
    except Exception as e:
        print(f"ERROR: Failed to generate fault dataset: {e}", file=sys.stderr)
        sys.exit(1)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = DecisionTreeClassifier(max_depth=6, random_state=42)
    clf.fit(X_train, y_train)

    accuracy = float(clf.score(X_test, y_test))

    out_h = root / "skyguard" / "edge" / "c" / "tiny_tree.h"
    out_c = root / "skyguard" / "edge" / "c" / "tiny_tree.c"

    fnames = ["step", "1h_change", "run_length", "td_minus_t", "var_ratio"]
    export_to_c(clf, fnames, out_h, out_c)

    # Save training metadata sidecar for build_host.py
    stats = {
        "training_data": training_data_desc,
        "accuracy": round(accuracy, 4),
        "node_count": int(clf.tree_.node_count),
        "max_depth": int(clf.get_depth()),
    }
    stats_path = root / "skyguard" / "edge" / "c" / "train_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Exported tiny_tree.c from dataset: '{training_data_desc}'")
    print(f"  Tree depth: {clf.get_depth()}, node count: {clf.tree_.node_count}")
    print(f"  Held-out test accuracy: {accuracy:.4f}")
    print(f"  Written to: {out_c}")


if __name__ == "__main__":
    main()
