import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("toml parser not found", file=sys.stderr)
        sys.exit(1)

def main():
    root = Path(__file__).resolve().parent.parent.parent
    config_path = root / "config" / "skyguard.toml"
    out_path = root / "skyguard" / "edge" / "c" / "thresholds.h"

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    rg = data.get("rule_gate", {})
    
    # defaults if not in config
    cfg = {
        "T_min": -40.0,
        "T_max": 60.0,
        "RH_min": 0.0,
        "RH_max": 103.0,
        "P_min": 600.0,
        "P_max": 1100.0,
        "frozen_hours": 6.0,
        "frozen_hours_integer": 12.0,
        "min_frozen_readings": 3,
        "fog_rh_threshold": 97.0,
        "fog_td_diff_max": 0.5,
        "td_max_above_t": 0.2,
    }
    for k in cfg:
        if k in rg:
            cfg[k] = rg[k]

    steps = rg.get("step", {
        "c1": {"T": 3.0, "RH": 10.0, "P": 0.5},
        "c15": {"T": 5.0, "RH": 20.0, "P": 1.5},
        "c30": {"T": 6.0, "RH": 25.0, "P": 2.0},
        "c60": {"T": 8.0, "RH": 30.0, "P": 3.0},
        "c180": {"T": 12.0, "RH": 40.0, "P": 6.0},
    })

    lines = [
        "#ifndef SKYGUARD_THRESHOLDS_H",
        "#define SKYGUARD_THRESHOLDS_H",
        "",
        "// Generated from config/skyguard.toml",
        ""
    ]

    for k, v in cfg.items():
        if isinstance(v, float):
            lines.append(f"#define RG_{k.upper()} {v}f")
        else:
            lines.append(f"#define RG_{k.upper()} {v}")

    lines.append("")
    lines.append("typedef struct {")
    lines.append("    float t_limit;")
    lines.append("    float rh_limit;")
    lines.append("    float p_limit;")
    lines.append("} rg_step_limits_t;")
    lines.append("")

    lines.append("static inline rg_step_limits_t rg_get_step_limits(int cadence_min) {")
    
    def format_step(name):
        s = steps[name]
        return f"{{ {s['T']}f, {s['RH']}f, {s['P']}f }}"

    lines.append(f"    if (cadence_min <= 1) return (rg_step_limits_t){format_step('c1')};")
    lines.append(f"    if (cadence_min <= 15) return (rg_step_limits_t){format_step('c15')};")
    lines.append(f"    if (cadence_min <= 30) return (rg_step_limits_t){format_step('c30')};")
    lines.append(f"    if (cadence_min <= 60) return (rg_step_limits_t){format_step('c60')};")
    lines.append(f"    return (rg_step_limits_t){format_step('c180')};")
    lines.append("}")
    lines.append("")
    lines.append("#endif // SKYGUARD_THRESHOLDS_H")
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
