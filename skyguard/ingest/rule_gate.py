"""Rule gate — fast pre-filter for obvious faults.  Owner: Person B.

Pure Python, no numpy.  Runs before the forecaster.  Decides gross range
(hard FAIL), dewpoint sanity (hard FAIL), step limits (SUSPECT), and
persistence/frozen values (SUSPECT).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"

_DEFAULT_CONFIG = {
    "T_min": -40.0,
    "T_max": 55.0,
    "RH_min": 0.0,
    "RH_max": 100.5,
    "P_min": 850.0,
    "P_max": 1085.0,
    "frozen_hours": 6.0,
    "frozen_hours_integer": 12.0,
    "min_frozen_readings": 3,
    "fog_rh_threshold": 97.0,
    "fog_td_diff_max": 0.5,
    "td_max_above_t": 0.2,
    "step": {
        "c1": {"T": 3.0, "RH": 10.0, "P": 0.5},
        "c15": {"T": 5.0, "RH": 20.0, "P": 1.5},
        "c30": {"T": 6.0, "RH": 25.0, "P": 2.0},
        "c60": {"T": 8.0, "RH": 30.0, "P": 3.0},
        "c180": {"T": 12.0, "RH": 40.0, "P": 6.0},
    },
}


_RG_CACHE: dict = {}


def load_rule_gate_config() -> dict:
    """Load [rule_gate] configuration (cached per file mtime; a fresh copy is returned each call)."""
    import copy
    try:
        mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None
    except OSError:
        mtime = None
    hit = _RG_CACHE.get("cfg")
    if hit is not None and hit[0] == mtime:
        return copy.deepcopy(hit[1])
    cfg = _load_rule_gate_config_uncached()
    _RG_CACHE["cfg"] = (mtime, cfg)
    return copy.deepcopy(cfg)


def _load_rule_gate_config_uncached() -> dict:
    """Load [rule_gate] configuration from skyguard.toml if present."""
    if CONFIG_PATH.exists() and tomllib is not None:
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                rg = data.get("rule_gate", {})
                cfg = dict(_DEFAULT_CONFIG)
                cfg.update({k: v for k, v in rg.items() if k != "step"})
                if "step" in rg:
                    cfg["step"] = rg["step"]
                return cfg
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO8601 UTC timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _get_step_thresholds(cfg: dict, cadence_min: int) -> dict[str, float]:
    """Get step limit thresholds for the nearest cadence at or above cadence_min."""
    step_cfg = cfg.get("step", _DEFAULT_CONFIG["step"])
    if cadence_min <= 1:
        key = "c1"
    elif cadence_min <= 15:
        key = "c15"
    elif cadence_min <= 30:
        key = "c30"
    elif cadence_min <= 60:
        key = "c60"
    else:
        key = "c180"
    return step_cfg.get(key, step_cfg["c180"])


def check(rows: list[dict], cadence_min: int = 15) -> dict[str, dict]:
    """Run rule-based checks on a short history of contract rows for ONE station.

    Returns dict per variable (T, RH, P) with:
      - fail: bool (Hard fail for gross out-of-range or Td > T + 0.2)
      - suspect: bool (Soft suspect for step limits or frozen values)
      - cause / root_cause: str | None
      - reason: str
      - tests: list[dict]
    """
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

    # Check for fog condition: RH >= fog_rh_threshold and T - Td <= fog_td_diff_max
    t_val = newest.get("T")
    td_val = newest.get("Td")
    rh_val = newest.get("RH")

    is_fog = False
    if rh_val is not None and rh_val >= cfg["fog_rh_threshold"]:
        if t_val is not None and td_val is not None and (t_val - td_val) <= cfg["fog_td_diff_max"]:
            is_fog = True

    # Parse timestamps for rows
    parsed_rows = []
    for r in rows:
        ts = r.get("ts_utc")
        if ts:
            try:
                dt = parse_ts(ts)
                parsed_rows.append((dt, r))
            except Exception:
                pass

    step_limits = _get_step_thresholds(cfg, cadence_min)

    # 1. Temperature (T)
    t_tests: list[dict] = []
    t_fail = False
    t_suspect = False
    t_cause = None
    t_reason = "OK"

    if t_val is not None:
        t_min, t_max = cfg["T_min"], cfg["T_max"]
        if t_val < t_min or t_val >= t_max:
            t_fail = True
            t_cause = "out_of_range"
            t_reason = f"T={t_val} outside [{t_min}, {t_max}]"
            t_tests.append({"code": "gross_range", "value": float(t_val), "threshold": t_max if t_val >= t_max else t_min, "outcome": "FAIL"})
        else:
            t_tests.append({"code": "gross_range", "value": float(t_val), "threshold": t_max, "outcome": "PASS"})

        # Step limit check (SUSPECT)
        if not t_fail and len(parsed_rows) > 1:
            dt_newest, r_newest = parsed_rows[-1]
            dt_prev, r_prev = parsed_rows[-2]
            prev_t = r_prev.get("T")
            if prev_t is not None and (dt_newest - dt_prev).total_seconds() <= (cadence_min * 60 * 1.5):
                diff = abs(t_val - prev_t)
                t_limit = step_limits["T"]
                if diff > t_limit:
                    t_suspect = True
                    t_cause = "spike"
                    t_reason = f"T step change {diff:.1f} > {t_limit:.1f}"
                    t_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(t_limit), "outcome": "SUSPECT"})
                else:
                    t_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(t_limit), "outcome": "PASS"})

        # Frozen window check (SUSPECT) — exempt if is_fog
        if not t_fail and not t_suspect and not is_fog and parsed_rows:
            source = newest.get("source")
            is_metar_speci = source in ("ghcnh_metar", "ghcnh_speci")
            req_hours = cfg["frozen_hours_integer"] if is_metar_speci else cfg["frozen_hours"]

            dt_newest = parsed_rows[-1][0]
            window_t = [(dt, r.get("T")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
            t_vals = [v for _, v in window_t if v is not None]

            if not is_metar_speci and t_vals and all(v == int(v) for v in t_vals):
                req_hours = cfg["frozen_hours_integer"]
                window_t = [(dt, r.get("T")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
                t_vals = [v for _, v in window_t if v is not None]

            if len(t_vals) >= cfg["min_frozen_readings"]:
                span_hours = (dt_newest - window_t[0][0]).total_seconds() / 3600.0
                expected_readings = span_hours * 60.0 / cadence_min
                if span_hours >= (req_hours - 0.05) and len(set(t_vals)) == 1 and len(t_vals) >= 0.5 * expected_readings:
                    t_suspect = True
                    t_cause = "frozen"
                    t_reason = f"T value {t_val} frozen for {span_hours:.1f} h (>= {req_hours} h)"
                    t_tests.append({"code": "frozen", "value": float(t_val), "threshold": float(req_hours), "outcome": "SUSPECT"})

    out["T"] = {
        "fail": t_fail,
        "flag": t_fail,
        "suspect": t_suspect,
        "cause": t_cause,
        "root_cause": t_cause,
        "reason": t_reason,
        "tests": t_tests,
    }

    # 2. Relative Humidity (RH) & Dewpoint (Td)
    rh_tests: list[dict] = []
    rh_fail = False
    rh_suspect = False
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

        # Dewpoint check: Td <= T + 0.2 (HARD FAIL)
        if not rh_fail and t_val is not None and td_val is not None:
            max_td = t_val + cfg["td_max_above_t"]
            if td_val > max_td:
                rh_fail = True
                rh_cause = "out_of_range"
                rh_reason = f"Td={td_val} > T+0.2 ({max_td:.1f})"
                rh_tests.append({"code": "dewpoint_limit", "value": float(td_val), "threshold": float(max_td), "outcome": "FAIL"})

        # Step limit check (SUSPECT)
        if not rh_fail and len(parsed_rows) > 1:
            dt_newest, r_newest = parsed_rows[-1]
            dt_prev, r_prev = parsed_rows[-2]
            prev_rh = r_prev.get("RH")
            if prev_rh is not None and (dt_newest - dt_prev).total_seconds() <= (cadence_min * 60 * 1.5):
                diff = abs(rh_val - prev_rh)
                rh_limit = step_limits["RH"]
                if diff > rh_limit:
                    rh_suspect = True
                    rh_cause = "spike"
                    rh_reason = f"RH step change {diff:.1f} > {rh_limit:.1f}"
                    rh_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(rh_limit), "outcome": "SUSPECT"})

        # Frozen window check (SUSPECT) — exempt if is_fog
        if not rh_fail and not rh_suspect and not is_fog and parsed_rows:
            source = newest.get("source")
            is_metar_speci = source in ("ghcnh_metar", "ghcnh_speci")
            req_hours = cfg["frozen_hours_integer"] if is_metar_speci else cfg["frozen_hours"]

            dt_newest = parsed_rows[-1][0]
            window_rh = [(dt, r.get("RH")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
            rh_vals = [v for _, v in window_rh if v is not None]

            if not is_metar_speci and rh_vals and all(v == int(v) for v in rh_vals):
                req_hours = cfg["frozen_hours_integer"]
                window_rh = [(dt, r.get("RH")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
                rh_vals = [v for _, v in window_rh if v is not None]

            if len(rh_vals) >= cfg["min_frozen_readings"]:
                span_hours = (dt_newest - window_rh[0][0]).total_seconds() / 3600.0
                expected_readings = span_hours * 60.0 / cadence_min
                if span_hours >= (req_hours - 0.05) and len(set(rh_vals)) == 1 and len(rh_vals) >= 0.5 * expected_readings:
                    rh_suspect = True
                    rh_cause = "frozen"
                    rh_reason = f"RH value {rh_val} frozen for {span_hours:.1f} h (>= {req_hours} h)"
                    rh_tests.append({"code": "frozen", "value": float(rh_val), "threshold": float(req_hours), "outcome": "SUSPECT"})

    out["RH"] = {
        "fail": rh_fail,
        "flag": rh_fail,
        "suspect": rh_suspect,
        "cause": rh_cause,
        "root_cause": rh_cause,
        "reason": rh_reason,
        "tests": rh_tests,
    }

    # 3. Pressure (P)
    p_val = newest.get("P")
    p_tests: list[dict] = []
    p_fail = False
    p_suspect = False
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

        # Step limit check (SUSPECT)
        if not p_fail and len(parsed_rows) > 1:
            dt_newest, r_newest = parsed_rows[-1]
            dt_prev, r_prev = parsed_rows[-2]
            prev_p = r_prev.get("P")
            if prev_p is not None and (dt_newest - dt_prev).total_seconds() <= (cadence_min * 60 * 1.5):
                diff = abs(p_val - prev_p)
                p_limit = step_limits["P"]
                if diff > p_limit:
                    p_suspect = True
                    p_cause = "spike"
                    p_reason = f"P step change {diff:.1f} > {p_limit:.1f}"
                    p_tests.append({"code": "step_limit", "value": float(diff), "threshold": float(p_limit), "outcome": "SUSPECT"})

        # Frozen window check (SUSPECT)
        if not p_fail and not p_suspect and parsed_rows:
            source = newest.get("source")
            is_metar_speci = source in ("ghcnh_metar", "ghcnh_speci")
            req_hours = cfg["frozen_hours_integer"] if is_metar_speci else cfg["frozen_hours"]

            dt_newest = parsed_rows[-1][0]
            window_p = [(dt, r.get("P")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
            p_vals = [v for _, v in window_p if v is not None]

            if not is_metar_speci and p_vals and all(v == int(v) for v in p_vals):
                req_hours = cfg["frozen_hours_integer"]
                window_p = [(dt, r.get("P")) for dt, r in parsed_rows if (dt_newest - dt).total_seconds() <= (req_hours * 3600 + 60)]
                p_vals = [v for _, v in window_p if v is not None]

            if len(p_vals) >= cfg["min_frozen_readings"]:
                span_hours = (dt_newest - window_p[0][0]).total_seconds() / 3600.0
                expected_readings = span_hours * 60.0 / cadence_min
                if span_hours >= (req_hours - 0.05) and len(set(p_vals)) == 1 and len(p_vals) >= 0.5 * expected_readings:
                    p_suspect = True
                    p_cause = "frozen"
                    p_reason = f"P value {p_val} frozen for {span_hours:.1f} h (>= {req_hours} h)"
                    p_tests.append({"code": "frozen", "value": float(p_val), "threshold": float(req_hours), "outcome": "SUSPECT"})

    out["P"] = {
        "fail": p_fail,
        "flag": p_fail,
        "suspect": p_suspect,
        "cause": p_cause,
        "root_cause": p_cause,
        "reason": p_reason,
        "tests": p_tests,
    }

    return out
