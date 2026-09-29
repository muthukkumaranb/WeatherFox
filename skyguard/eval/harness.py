"""Evaluation harness — event-wise metrics per variable x root cause. Owner: Person B.

Measures precision, recall, F1, detection delay, clean false-alarm rate,
and genuine-event false alarms without applying point-adjust.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable, Union


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string into UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_jsonl_or_list(data_or_path: Union[list[dict], str, Path]) -> list[dict]:
    if isinstance(data_or_path, (str, Path)):
        path = Path(data_or_path)
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return items
    return data_or_path


def evaluate(
    verdicts_input: Union[list[dict], str, Path],
    labels_input: Union[list[dict], str, Path],
    events_cfg: dict | None = None,
    tolerance_seconds: float = 3600.0,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run full evaluation suite and return metrics dict.

    Optionally writes metrics.json and metrics.md to output_dir if provided.
    """
    verdicts = _load_jsonl_or_list(verdicts_input)
    labels = _load_jsonl_or_list(labels_input)

    # Sort verdicts by timestamp
    verdicts_sorted = sorted(verdicts, key=lambda v: _parse_ts(v["ts_utc"]))

    # Separate provisional vs final verdicts
    final_verdicts = [v for v in verdicts_sorted if v.get("phase", "final") == "final"]
    provisional_verdicts = [v for v in verdicts_sorted if v.get("phase") == "provisional"]

    # Filter fault labels vs genuine event labels
    fault_labels = [lbl for lbl in labels if not lbl.get("genuine_event", False)]
    genuine_event_labels = [lbl for lbl in labels if lbl.get("genuine_event", False)]

    # 1. Event-wise Recall, Detection Delay, and Root Cause metrics
    # Group fault labels by (variable, root_cause)
    class_events: dict[tuple[str, str], list[dict]] = {}
    for lbl in fault_labels:
        var = lbl.get("variable", "T")
        rc = lbl.get("root_cause", "unknown")
        class_events.setdefault((var, rc), []).append(lbl)

    # Map final verdicts by station_id
    verdicts_by_station: dict[str, list[dict]] = {}
    for v in final_verdicts:
        verdicts_by_station.setdefault(v["station_id"], []).append(v)

    per_class_metrics: dict[str, dict[str, Any]] = {}
    delays_by_class: dict[str, list[float]] = {}

    total_fault_events = len(fault_labels)
    total_detected_events = 0

    for (var, rc), ev_list in class_events.items():
        key_name = f"{var} x {rc}"
        detected_count = 0
        class_delays = []

        for ev in ev_list:
            st = ev["station_id"]
            start_dt = _parse_ts(ev["start_ts"])
            end_dt = _parse_ts(ev["end_ts"])
            tol_end_dt = datetime.fromtimestamp(end_dt.timestamp() + tolerance_seconds, tz=timezone.utc)

            st_verdicts = verdicts_by_station.get(st, [])
            first_detection_ts: datetime | None = None

            for v in st_verdicts:
                v_dt = _parse_ts(v["ts_utc"])
                if start_dt <= v_dt <= tol_end_dt:
                    # Check if anomaly flagged for target variable or overall
                    v_vars = v.get("vars", {})
                    var_info = v_vars.get(var, {})
                    is_anomaly = (var_info.get("label") == "anomaly") or (v.get("label") == "anomaly")

                    if is_anomaly:
                        if first_detection_ts is None:
                            first_detection_ts = v_dt
                        break

            if first_detection_ts is not None:
                detected_count += 1
                delay_sec = max(0.0, (first_detection_ts - start_dt).total_seconds())
                class_delays.append(delay_sec)

        recall = detected_count / len(ev_list) if ev_list else 0.0
        delays_by_class[key_name] = class_delays
        total_detected_events += detected_count

        if class_delays:
            sorted_d = sorted(class_delays)
            p50_delay = sorted_d[len(sorted_d) // 2]
            p90_delay = sorted_d[int(len(sorted_d) * 0.9)]
        else:
            p50_delay = None
            p90_delay = None

        per_class_metrics[key_name] = {
            "n_events": len(ev_list),
            "detected": detected_count,
            "recall": recall,
            "delay_p50_sec": p50_delay,
            "delay_p90_sec": p90_delay,
        }

    # 2. Precision over Grouped Alert Incidents (NO point adjust!)
    # Group consecutive anomaly verdicts into incidents per station & variable
    incidents: list[dict] = []
    for st, st_verdicts in verdicts_by_station.items():
        st_verdicts_sorted = sorted(st_verdicts, key=lambda v: _parse_ts(v["ts_utc"]))

        for var in ("T", "RH", "P"):
            in_incident = False
            inc_start: datetime | None = None
            inc_end: datetime | None = None

            for v in st_verdicts_sorted:
                v_dt = _parse_ts(v["ts_utc"])
                var_info = v.get("vars", {}).get(var, {})
                is_anom = var_info.get("label") == "anomaly"

                if is_anom:
                    if not in_incident:
                        in_incident = True
                        inc_start = v_dt
                    inc_end = v_dt
                else:
                    if in_incident:
                        incidents.append({
                            "station_id": st,
                            "variable": var,
                            "start_dt": inc_start,
                            "end_dt": inc_end,
                        })
                        in_incident = False

            if in_incident:
                incidents.append({
                    "station_id": st,
                    "variable": var,
                    "start_dt": inc_start,
                    "end_dt": inc_end,
                })

    # Evaluate incidents: check if overlapping with any ground-truth fault event
    tp_incidents = 0
    fp_incidents = 0

    for inc in incidents:
        st = inc["station_id"]
        var = inc["variable"]
        inc_s = inc["start_dt"]
        inc_e = inc["end_dt"]

        matched = False
        for lbl in fault_labels:
            if lbl["station_id"] == st and (lbl.get("variable") in (var, "all")):
                ev_s = _parse_ts(lbl["start_ts"])
                ev_e = _parse_ts(lbl["end_ts"])
                # Check interval overlap
                if max(inc_s, ev_s) <= min(inc_e, ev_e):
                    matched = True
                    break
        if matched:
            tp_incidents += 1
        else:
            fp_incidents += 1

    total_incidents = tp_incidents + fp_incidents
    precision = tp_incidents / total_incidents if total_incidents > 0 else 1.0
    overall_recall = total_detected_events / total_fault_events if total_fault_events > 0 else 1.0
    f1_score = (2 * precision * overall_recall) / (precision + overall_recall) if (precision + overall_recall) > 0 else 0.0

    # 3. Clean False Alarm Rate
    # Count anomaly verdicts outside any fault injection window & outside genuine weather events
    clean_verdicts_count = 0
    clean_false_alarms = 0

    for v in final_verdicts:
        st = v["station_id"]
        v_dt = _parse_ts(v["ts_utc"])

        in_fault_window = False
        for lbl in fault_labels:
            if lbl["station_id"] == st:
                s = _parse_ts(lbl["start_ts"])
                e = _parse_ts(lbl["end_ts"])
                if s <= v_dt <= e:
                    in_fault_window = True
                    break

        in_genuine_window = False
        for lbl in genuine_event_labels:
            if lbl.get("station_id") == st:
                s = _parse_ts(lbl["start_ts"])
                e = _parse_ts(lbl["end_ts"])
                if s <= v_dt <= e:
                    in_genuine_window = True
                    break

        if not in_fault_window and not in_genuine_window:
            clean_verdicts_count += 1
            if v.get("label") == "anomaly":
                clean_false_alarms += 1

    clean_far = clean_false_alarms / clean_verdicts_count if clean_verdicts_count > 0 else 0.0

    # 4. Genuine Event False Alarms per 100 station-days
    genuine_false_alarms = 0
    genuine_verdict_count = 0
    for v in final_verdicts:
        st = v["station_id"]
        v_dt = _parse_ts(v["ts_utc"])
        for lbl in genuine_event_labels:
            if lbl.get("station_id") == st:
                s = _parse_ts(lbl["start_ts"])
                e = _parse_ts(lbl["end_ts"])
                if s <= v_dt <= e:
                    genuine_verdict_count += 1
                    if v.get("label") == "anomaly":
                        genuine_false_alarms += 1
                    break

    # Estimate station-days: assuming 15m cadence (96 readings/day) or timestamp span
    st_days = max(1.0, genuine_verdict_count / 96.0)
    genuine_fa_per_100_st_days = (genuine_false_alarms / st_days) * 100.0

    # 5. Provisional vs Final Accuracy
    provisional_agreements = 0
    if provisional_verdicts and final_verdicts:
        prov_map = {(v["station_id"], v["ts_utc"]): v.get("label") for v in provisional_verdicts}
        total_compared = 0
        for fv in final_verdicts:
            key = (fv["station_id"], fv["ts_utc"])
            if key in prov_map:
                total_compared += 1
                if prov_map[key] == fv.get("label"):
                    provisional_agreements += 1
        prov_vs_final_acc = provisional_agreements / total_compared if total_compared > 0 else 1.0
    else:
        prov_vs_final_acc = 1.0

    # 6. Latency P50 / P95
    latencies = [v["latency_ms"] for v in final_verdicts if "latency_ms" in v]
    if latencies:
        sorted_lat = sorted(latencies)
        lat_p50 = sorted_lat[len(sorted_lat) // 2]
        lat_p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
    else:
        lat_p50 = None
        lat_p95 = None

    metrics_out: dict[str, Any] = {
        "summary": {
            "total_fault_events": total_fault_events,
            "detected_fault_events": total_detected_events,
            "event_recall": overall_recall,
            "incident_precision": precision,
            "f1_score": f1_score,
            "clean_false_alarm_rate": clean_far,
            "clean_false_alarms_count": clean_false_alarms,
            "clean_verdicts_count": clean_verdicts_count,
            "genuine_event_fa_per_100_st_days": genuine_fa_per_100_st_days,
            "provisional_vs_final_accuracy": prov_vs_final_acc,
            "latency_p50_ms": lat_p50,
            "latency_p95_ms": lat_p95,
        },
        "per_class": per_class_metrics,
        "total_verdicts": len(verdicts),
        "total_labels": len(labels),
    }

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        # Write metrics.json
        (out_p / "metrics.json").write_text(json.dumps(metrics_out, indent=2), encoding="utf-8")

        # Write metrics.md (tables)
        md_lines = [
            "# SkyGuard Evaluation Metrics Report",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Total Fault Events | {total_fault_events} |",
            f"| Event-wise Recall | {overall_recall:.4f} |",
            f"| Incident-wise Precision | {precision:.4f} |",
            f"| **F1 Score** | **{f1_score:.4f}** |",
            f"| Clean False Alarm Rate | {clean_far:.4f} ({clean_false_alarms}/{clean_verdicts_count}) |",
            f"| Genuine Event FAs / 100 station-days | {genuine_fa_per_100_st_days:.2f} |",
            f"| Provisional vs Final Accuracy | {prov_vs_final_acc:.4f} |",
            "",
            "## Per-Class Breakdown (Variable x Root Cause)",
            "",
            "| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |",
            "|---|---|---|---|---|---|",
        ]

        for cls_name, info in per_class_metrics.items():
            cnt = info["n_events"]
            det = info["detected"]
            # Use raw counts for < 50 events as required!
            rec_str = f"{det}/{cnt}" if cnt < 50 else f"{info['recall']:.2%}"
            p50_str = f"{info['delay_p50_sec']:.1f}" if info['delay_p50_sec'] is not None else "N/A"
            p90_str = f"{info['delay_p90_sec']:.1f}" if info['delay_p90_sec'] is not None else "N/A"
            md_lines.append(f"| {cls_name} | {cnt} | {det} | {rec_str} | {p50_str} | {p90_str} |")

        (out_p / "metrics.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return metrics_out


def main() -> None:
    parser = argparse.ArgumentParser(description="SkyGuard Evaluation Harness")
    parser.add_argument("--verdicts", type=str, required=True, help="Path to verdicts JSONL")
    parser.add_argument("--labels", type=str, required=True, help="Path to injection labels JSONL")
    parser.add_argument("--out", type=str, required=True, help="Output directory for reports")
    args = parser.parse_args()

    res = evaluate(args.verdicts, args.labels, output_dir=args.out)
    print(f"✅ Evaluation complete. F1 Score: {res['summary']['f1_score']:.4f}")
    print(f"   Reports written to {args.out}")


if __name__ == "__main__":
    main()
