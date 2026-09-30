import sys
import os
import shutil
import subprocess
import time
import json
import platform
import tempfile
from pathlib import Path

def get_gcc_version(gcc_path):
    try:
        out = subprocess.check_output([gcc_path, "--version"], text=True)
        return out.splitlines()[0]
    except Exception:
        return "gcc unknown"

def get_cpu_info():
    proc = platform.processor()
    if proc:
        return proc
    mach = platform.machine()
    if os.path.exists("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return mach or "unknown CPU"

def main():
    gcc_path = shutil.which("gcc")
    if not gcc_path:
        print("gcc not found — run this on Linux/Codespaces")
        sys.exit(1)

    root = Path(__file__).resolve().parent.parent.parent
    c_dir = root / "skyguard" / "edge" / "c"
    reports_edge_dir = root / "reports" / "edge"
    reports_edge_dir.mkdir(parents=True, exist_ok=True)

    rule_gate_c = c_dir / "rule_gate.c"
    tiny_tree_c = c_dir / "tiny_tree.c"

    if not rule_gate_c.exists() or not tiny_tree_c.exists():
        print("Error: Missing C source files in skyguard/edge/c/", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        rule_gate_o = tmp_path / "rule_gate.o"
        tiny_tree_o = tmp_path / "tiny_tree.o"

        # Compile object files with -Os
        cmd_rg = [gcc_path, "-Os", "-c", str(rule_gate_c), "-I", str(c_dir), "-o", str(rule_gate_o)]
        subprocess.run(cmd_rg, check=True)

        cmd_tt = [gcc_path, "-Os", "-c", str(tiny_tree_c), "-I", str(c_dir), "-o", str(tiny_tree_o)]
        subprocess.run(cmd_tt, check=True)

        size_rg = os.path.getsize(rule_gate_o)
        size_tt = os.path.getsize(tiny_tree_o)

        # Generate 10,000 synthetic rows for test harness
        import random
        random.seed(42)

        rows = []
        c_csv_lines = []
        for i in range(10000):
            ts_str = f"2024-01-01T{(i // 60) % 24:02d}:{i % 60:02d}:00Z"
            ts_sec = 1704067200 + i * 60
            # Inject some anomalies
            if i % 500 == 0:
                t_val = 70.0  # Fail gross range
            elif i % 300 == 0:
                t_val = -50.0 # Fail gross range
            elif i % 200 == 0:
                t_val = 25.0 + (i % 10) * 4.0 # Step change
            else:
                t_val = 25.0 + random.uniform(-1.0, 1.0)
            
            rh_val = 50.0 + random.uniform(-5.0, 5.0)
            p_val = 1013.0 + random.uniform(-2.0, 2.0)
            td_val = t_val - ((100.0 - rh_val) / 5.0)

            rows.append({
                "station_id": "test_stn",
                "ts_utc": ts_str,
                "T": t_val,
                "RH": rh_val,
                "P": p_val,
                "Td": td_val,
                "cadence_min": 15,
                "is_metar_speci": False,
                "source": "esp32"
            })
            c_csv_lines.append(f"{t_val:.2f},{td_val:.2f},{rh_val:.2f},{p_val:.2f},15,0,{ts_sec}")

        csv_file = tmp_path / "input.csv"
        csv_file.write_text("\n".join(c_csv_lines))

        # Create C harness
        harness_c = tmp_path / "harness.c"
        harness_code = """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "rule_gate.h"
#include "tiny_tree.h"

int main(int argc, char** argv) {
    if (argc < 2) return 1;
    FILE* f = fopen(argv[1], "r");
    if (!f) return 1;

    rg_row_t rows[10000];
    int count = 0;

    float t, td, rh, p;
    int cadence, is_metar;
    long long ts;

    while (fscanf(f, "%f,%f,%f,%f,%d,%d,%lld", &t, &td, &rh, &p, &cadence, &is_metar, &ts) == 7 && count < 10000) {
        rows[count].T = t;
        rows[count].Td = td;
        rows[count].RH = rh;
        rows[count].P = p;
        rows[count].has_T = 1;
        rows[count].has_Td = 1;
        rows[count].has_RH = 1;
        rows[count].has_P = 1;
        rows[count].cadence_min = cadence;
        rows[count].is_metar_speci = is_metar;
        rows[count].ts_utc = ts;
        count++;
    }
    fclose(f);

    FILE* out_f = fopen(argv[2], "w");
    if (!out_f) return 1;

    for (int i = 0; i < count; i++) {
        // Run window up to row i
        rg_result_t res = rg_check(rows, i + 1);
        int tree_res = 0;
        float features[5] = {0.0f, 0.0f, 1.0f, rows[i].Td - rows[i].T, 1.0f};
        if (i > 0) {
            features[0] = rows[i].T - rows[i-1].T;
        }
        tree_res = tree_predict(features);

        int fail = (res.status_T == RG_FAIL || res.status_RH == RG_FAIL || res.status_P == RG_FAIL);
        int suspect = (res.status_T == RG_SUSPECT || res.status_RH == RG_SUSPECT || res.status_P == RG_SUSPECT);
        fprintf(out_f, "%d,%d,%d\\n", fail, suspect, tree_res);
    }
    fclose(out_f);
    return 0;
}
"""
        harness_c.write_text(harness_code)

        harness_exe = tmp_path / ("harness.exe" if sys.platform == "win32" else "harness")
        cmd_harness = [gcc_path, "-Os", str(harness_c), str(rule_gate_o), str(tiny_tree_o), "-I", str(c_dir), "-lm", "-o", str(harness_exe)]
        subprocess.run(cmd_harness, check=True)

        out_results_file = tmp_path / "c_out.txt"

        # Time C harness execution
        t0 = time.perf_counter()
        subprocess.run([str(harness_exe), str(csv_file), str(out_results_file)], check=True)
        t1 = time.perf_counter()

        c_time_sec = t1 - t0
        us_per_reading = (c_time_sec / 10000.0) * 1e6

        # Read C outcomes
        c_results = []
        for line in out_results_file.read_text().strip().splitlines():
            if line:
                f_val, s_val, tr_val = map(int, line.split(","))
                c_results.append((f_val, s_val, tr_val))

        # Run Python rule_gate row by row
        sys.path.insert(0, str(root))
        from skyguard.ingest.rule_gate import check as py_check

        py_results = []
        for i in range(len(rows)):
            window = rows[:i+1]
            py_res = py_check(window, cadence_min=15)
            py_fail = 1 if (py_res["T"]["fail"] or py_res["RH"]["fail"] or py_res["P"]["fail"]) else 0
            py_suspect = 1 if (py_res["T"]["suspect"] or py_res["RH"]["suspect"] or py_res["P"]["suspect"]) else 0
            py_results.append((py_fail, py_suspect))

        parity_agreed = 0
        parity_total = len(rows)

        for i in range(parity_total):
            c_fail, c_suspect, _ = c_results[i]
            py_fail, py_suspect = py_results[i]
            if (c_fail == py_fail) and (c_suspect == py_suspect):
                parity_agreed += 1

        gcc_ver = get_gcc_version(gcc_path)
        cpu_name = get_cpu_info()
        measured_on = f"{gcc_ver} on {cpu_name}"

        edge_json = {
            "parity_agreed": parity_agreed,
            "parity_total": parity_total,
            "object_sizes": {
                "rule_gate.o": size_rg,
                "tiny_tree.o": size_tt
            },
            "us_per_reading": round(us_per_reading, 3),
            "gcc_version": gcc_ver,
            "measured_on": measured_on,
            "label": "host-measured estimate, not ESP32 hardware"
        }

        out_json_path = reports_edge_dir / "edge.json"
        with open(out_json_path, "w") as f:
            json.dump(edge_json, f, indent=2)

        print(f"Successfully compiled and measured edge harness. Output written to {out_json_path}")

if __name__ == "__main__":
    main()
