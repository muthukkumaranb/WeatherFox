"""Calibration check on clean val_eval data (no injected faults).

What the conformal layer guarantees is per variable: with alpha_uncertain = 0.01 (per variable x cadence,
calibrated on val_cal), each of T, RH and P should be flagged "uncertain" by the model on about 1 % of clean
readings. Across three variables plus rule-gate step/frozen flags the per-READING uncertain rate is therefore
about 3-4 % by construction; it is printed here, not asserted against a 3 % reading-level gate.

Asserted:
  * reading-level anomaly rate < 1 %
  * per-variable model-only uncertain rate < 2 x alpha_uncertain
Runs on a fixed subset of val_eval stations to keep the test under a couple of minutes.
"""
import json
import math
import os
from pathlib import Path

import pytest

VAL = Path("splits/val_eval.jsonl")
MODEL = Path("models/detector.pkl")
N_STATIONS = 8


def _load_clean_subset() -> list[dict]:
    rows_by = {}
    with open(VAL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            for k in ("lat", "lon", "name"):
                r.pop(k, None)
            for k, v in list(r.items()):
                if isinstance(v, float) and math.isnan(v):
                    r[k] = None
            rows_by.setdefault(r["station_id"], []).append(r)
    keep = sorted(rows_by)[:N_STATIONS]
    return [r for sid in keep for r in rows_by[sid]]


@pytest.mark.skipif(not (VAL.exists() and MODEL.exists()), reason="val_eval split or trained model missing")
def test_clean_val_calibration():
    os.environ["SKYGUARD_SCORER"] = "real"
    import pandas as pd

    from skyguard.detect.conformal import get_config
    from skyguard.verdict.batch import score_all_batch

    alpha_u = float(get_config().get("conformal", {}).get("alpha_uncertain", 0.01))
    verdicts = score_all_batch(pd.DataFrame(_load_clean_subset()))
    n = len(verdicts)
    assert n > 1000

    n_anom = sum(v["label"] == "anomaly" for v in verdicts)
    n_unc = sum(v["label"] == "uncertain" for v in verdicts)
    model_unc = {"T": 0, "RH": 0, "P": 0}
    for v in verdicts:
        for var, r in (v.get("vars") or {}).items():
            feats = [x.get("feature", "") for x in r.get("reasons", [])]
            if var in model_unc and r.get("label") == "uncertain" and not any(f.startswith("rule") for f in feats):
                model_unc[var] += 1

    print(f"clean readings {n}: anomaly {n_anom / n:.4f}, uncertain {n_unc / n:.4f} (reading level, 3 variables)")
    for var, k in model_unc.items():
        print(f"  {var}: model-only uncertain {k / n:.4f} (alpha_uncertain {alpha_u})")

    assert n_anom / n < 0.01, f"clean anomaly rate {n_anom / n:.4f} >= 1 %"
    for var, k in model_unc.items():
        assert k / n < 2 * alpha_u, f"{var} model uncertain rate {k / n:.4f} >= 2 x alpha ({2 * alpha_u})"
