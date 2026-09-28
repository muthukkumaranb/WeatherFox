"""Rule gate — fast pre-filter for obvious faults.  Owner: Person B.

Pure Python, no numpy.  Runs before the forecaster.  Decides gross range,
step limits, persistence/frozen values, and dewpoint sanity.
"""
from __future__ import annotations

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"

_DEFAULT_CONFIG = {
    "T_min": -40.0,
    "T_max": 60.0,
    "RH_min": 0.0,
    "RH_max": 103.0,
    "P_min": 600.0,
    "P_max": 1100.0,
    "T_step_per_min": 0.5,
    "RH_step_per_min": 2.0,
    "P_step_per_min": 0.5,
    "min_frozen_steps": 4,
    "fog_rh_threshold": 97.0,
    "fog_td_diff_max": 0.5,
    "td_max_above_t": 0.2,
}


def load_rule_gate_config() -> dict:
    """Load [rule_gate] configuration from skyguard.toml if present."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                cfg = dict(_DEFAULT_CONFIG)
                cfg.update(data.get("rule_gate", {}))
                return cfg
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def check(rows: list[dict], cadence_min: int = 15) -> dict[str, dict]:
    """Run rule-based checks on a short history of contract rows for ONE station."""
    cfg = load_rule_gate_config()
    out: dict[str, dict] = {}

    if not rows:
        for var in ("T", "RH", "P"):
            out[var] = {
                "fail": False,
                "flag": False,
                "suspect": False,
                "cause": None,
                "root_cause": None,
                "reason": "OK",
                "tests": [],
            }
        return out

    newest = rows[-1]

    # 1. Temperature (T)
    t_val = newest.get("T")
    t_tests: list[dict] = []
    t_fail = False
    t_cause = None
    t_reason = "OK"

    if t_val is not None:
        t_min, t_max = cfg["T_min"], cfg["T_max"]
        if t_val < t_min or t_val > t_max:
            t_fail = True
            t_cause = "out_of_range"
            t_reason = f"T={t_val} outside [{t_min}, {t_max}]"
            t_tests.append({"code": "gross_range", "value": float(t_val), "threshold": t_max if t_val > t_max else t_min, "outcome": "FAIL"})
        else:
            t_tests.append({"code": "gross_range", "value": float(t_val), "threshold": t_max, "outcome": "PASS"})

        # Step limit check
        if not t_fail and len(rows) > 1:
            prev_t = rows[-2].get("T")
            if prev_t is not None:
                step_limit = cfg["T_step_per_min"] * cadence_min
                diff = abs(t_val - prev_t)
                if diff > step_limit:
                    t_fail = True
                    t_cause = "spike"
                    t_reason = f"T step change {diff:.1f} > {step_limit:.1f}"
                    t_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(step_limit), "outcome": "FAIL"})
                else:
                    t_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(step_limit), "outcome": "PASS"})

        # Persistence / frozen check
        if not t_fail and len(rows) >= cfg["min_frozen_steps"]:
            recent_t = [r.get("T") for r in rows[-cfg["min_frozen_steps"]:]]
            if all(x is not None for x in recent_t) and len(set(recent_t)) == 1:
                t_fail = True
                t_cause = "frozen"
                t_reason = f"T value {t_val} frozen for {cfg['min_frozen_steps']} steps"
                t_tests.append({"code": "frozen", "value": float(t_val), "threshold": float(cfg["min_frozen_steps"]), "outcome": "FAIL"})
            else:
                t_tests.append({"code": "frozen", "value": float(t_val), "threshold": float(cfg["min_frozen_steps"]), "outcome": "PASS"})

    out["T"] = {
        "fail": t_fail,
        "flag": t_fail,
        "suspect": False,
        "cause": t_cause,
        "root_cause": t_cause,
        "reason": t_reason,
        "tests": t_tests,
    }

    # 2. Relative Humidity (RH) & Dewpoint (Td)
    rh_val = newest.get("RH")
    td_val = newest.get("Td")
    rh_tests: list[dict] = []
    rh_fail = False
    rh_cause = None
    rh_reason = "OK"

    if rh_val is not None:
        rh_min, rh_max = cfg["RH_min"], cfg["RH_max"]
        if rh_val < rh_min or rh_val > rh_max:
            rh_fail = True
            rh_cause = "out_of_range"
            rh_reason = f"RH={rh_val} outside [{rh_min}, {rh_max}]"
            rh_tests.append({"code": "gross_range", "value": float(rh_val), "threshold": rh_max if rh_val > rh_max else rh_min, "outcome": "FAIL"})
        else:
            rh_tests.append({"code": "gross_range", "value": float(rh_val), "threshold": rh_max, "outcome": "PASS"})

        # Dewpoint check: Td <= T + 0.2
        if not rh_fail and t_val is not None and td_val is not None:
            max_td = t_val + cfg["td_max_above_t"]
            if td_val > max_td:
                rh_fail = True
                rh_cause = "out_of_range"
                rh_reason = f"Td={td_val} > T+0.2 ({max_td:.1f})"
                rh_tests.append({"code": "dewpoint_limit", "value": float(td_val), "threshold": float(max_td), "outcome": "FAIL"})

        # Step limit check
        if not rh_fail and len(rows) > 1:
            prev_rh = rows[-2].get("RH")
            if prev_rh is not None:
                step_limit = cfg["RH_step_per_min"] * cadence_min
                diff = abs(rh_val - prev_rh)
                if diff > step_limit:
                    rh_fail = True
                    rh_cause = "spike"
                    rh_reason = f"RH step change {diff:.1f} > {step_limit:.1f}"
                    rh_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(step_limit), "outcome": "FAIL"})

        # Persistence / frozen check (with fog exemption)
        if not rh_fail and len(rows) >= cfg["min_frozen_steps"]:
            recent_rh = [r.get("RH") for r in rows[-cfg["min_frozen_steps"]:]]
            if all(x is not None for x in recent_rh) and len(set(recent_rh)) == 1:
                # Check fog exemption: RH >= fog_rh_threshold and Td close to T
                is_fog = False
                if rh_val >= cfg["fog_rh_threshold"] and t_val is not None and td_val is not None:
                    if abs(t_val - td_val) <= cfg["fog_td_diff_max"]:
                        is_fog = True
                if not is_fog:
                    rh_fail = True
                    rh_cause = "frozen"
                    rh_reason = f"RH value {rh_val} frozen for {cfg['min_frozen_steps']} steps"
                    rh_tests.append({"code": "frozen", "value": float(rh_val), "threshold": float(cfg["min_frozen_steps"]), "outcome": "FAIL"})

    out["RH"] = {
        "fail": rh_fail,
        "flag": rh_fail,
        "suspect": False,
        "cause": rh_cause,
        "root_cause": rh_cause,
        "reason": rh_reason,
        "tests": rh_tests,
    }

    # 3. Pressure (P)
    p_val = newest.get("P")
    p_tests: list[dict] = []
    p_fail = False
    p_cause = None
    p_reason = "OK"

    if p_val is not None:
        p_min, p_max = cfg["P_min"], cfg["P_max"]
        if p_val < p_min or p_val > p_max:
            p_fail = True
            p_cause = "out_of_range"
            p_reason = f"P={p_val} outside [{p_min}, {p_max}]"
            p_tests.append({"code": "gross_range", "value": float(p_val), "threshold": p_max if p_val > p_max else p_min, "outcome": "FAIL"})
        else:
            p_tests.append({"code": "gross_range", "value": float(p_val), "threshold": p_max, "outcome": "PASS"})

        # Step limit check
        if not p_fail and len(rows) > 1:
            prev_p = rows[-2].get("P")
            if prev_p is not None:
                step_limit = cfg["P_step_per_min"] * cadence_min
                diff = abs(p_val - prev_p)
                if diff > step_limit:
                    p_fail = True
                    p_cause = "spike"
                    p_reason = f"P step change {diff:.1f} > {step_limit:.1f}"
                    p_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(step_limit), "outcome": "FAIL"})

        # Persistence / frozen check
        if not p_fail and len(rows) >= cfg["min_frozen_steps"]:
            recent_p = [r.get("P") for r in rows[-cfg["min_frozen_steps"]:]]
            if all(x is not None for x in recent_p) and len(set(recent_p)) == 1:
                p_fail = True
                p_cause = "frozen"
                p_reason = f"P value {p_val} frozen for {cfg['min_frozen_steps']} steps"
                p_tests.append({"code": "frozen", "value": float(p_val), "threshold": float(cfg["min_frozen_steps"]), "outcome": "FAIL"})

    out["P"] = {
        "fail": p_fail,
        "flag": p_fail,
        "suspect": False,
        "cause": p_cause,
        "root_cause": p_cause,
        "reason": p_reason,
        "tests": p_tests,
    }

    return out
