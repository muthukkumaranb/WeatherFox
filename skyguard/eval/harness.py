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

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"


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


def load_harness_config() -> dict:
    cfg = {"max_incident_hours": 24.0, "max_gap_hours": 1.0, "alert_budget": 0.05}
    if CONFIG_PATH.exists() and tomllib is not None:
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                h_cfg = data.get("harness", {})
                cfg.update(h_cfg)
        except Exception:
            pass
    return cfg


def load_genuine_events_config() -> list[dict]:
    events = []
    if CONFIG_PATH.exists() and tomllib is not None:
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                events = data.get("genuine_events", {}).get("events", [])
        except Exception:
            pass

    events_file = Path("data/labels/events.jsonl")
    if events_file.exists():
        try:
            with events_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        except Exception:
            pass
    return events


def _split_into_incidents(
    verdicts_sorted: list[dict],
    max_incident_hours: float = 24.0,
    max_gap_hours: float = 1.0,
) -> list[dict]:
    """Group consecutive anomaly verdicts into incidents per station & variable.

    Splits a run of consecutive anomalies into separate incidents every `max_incident_hours`
    and after any timestamp gap exceeding `max_gap_hours`.
    """
    by_station: dict[str, list[dict]] = {}
    for v in verdicts_sorted:
        by_station.setdefault(v["station_id"], []).append(v)

    incidents = []

    for st, st_verdicts in by_station.items():
        st_verdicts_sorted = sorted(st_verdicts, key=lambda v: _parse_ts(v["ts_utc"]))

        for var in ("T", "RH", "P"):
            current_incident: list[dict] = []

            for v in st_verdicts_sorted:
                v_dt = _parse_ts(v["ts_utc"])
                var_info = v.get("vars", {}).get(var, {})
                is_anom = (var_info.get("label") == "anomaly") or (v.get("label") == "anomaly" and var == "T")

                if is_anom:
                    if not current_incident:
                        current_incident.append(v)
                    else:
                        first_dt = _parse_ts(current_incident[0]["ts_utc"])
                        last_dt = _parse_ts(current_incident[-1]["ts_utc"])

                        dur_hours = (v_dt - first_dt).total_seconds() / 3600.0
                        gap_hours = (v_dt - last_dt).total_seconds() / 3600.0

                        if dur_hours > max_incident_hours or gap_hours > max_gap_hours:
                            # Finalize previous incident
                            incidents.append({
                                "station_id": st,
                                "variable": var,
                                "start_dt": first_dt,
                                "end_dt": last_dt,
                                "count": len(current_incident),
                            })
                            current_incident = [v]
                        else:
                            current_incident.append(v)
                else:
                    if current_incident:
                        first_dt = _parse_ts(current_incident[0]["ts_utc"])
                        last_dt = _parse_ts(current_incident[-1]["ts_utc"])
                        incidents.append({
                            "station_id": st,
                            "variable": var,
                            "start_dt": first_dt,
                            "end_dt": last_dt,
                            "count": len(current_incident),
                        })
                        current_incident = []

            if current_incident:
                first_dt = _parse_ts(current_incident[0]["ts_utc"])
                last_dt = _parse_ts(current_incident[-1]["ts_utc"])
                incidents.append({
                    "station_id": st,
                    "variable": var,
                    "start_dt": first_dt,
                    "end_dt": last_dt,
                    "count": len(current_incident),
                })

    return incidents


def evaluate(
    verdicts_input: Union[list[dict], str, Path],
    labels_input: Union[list[dict], str, Path],
    events_cfg: dict | list[dict] | None = None,
    tolerance_seconds: float = 3600.0,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run full evaluation suite and return metrics dict."""
    verdicts = _load_jsonl_or_list(verdicts_input)
    labels = _load_jsonl_or_list(labels_input)

    h_cfg = load_harness_config()
    max_inc_hours = h_cfg["max_incident_hours"]
    max_gap_hours = h_cfg["max_gap_hours"]
    alert_budget = h_cfg["alert_budget"]

    # Load genuine events
    if isinstance(events_cfg, list):
        genuine_events_list = events_cfg
    elif isinstance(events_cfg, dict):
        genuine_events_list = events_cfg.get("events", [events_cfg])
    else:
        genuine_events_list = load_genuine_events_config()

    verdicts_sorted = sorted(verdicts, key=lambda v: _parse_ts(v["ts_utc"]))
    final_verdicts = [v for v in verdicts_sorted if v.get("phase", "final") == "final"]
    provisional_verdicts = [v for v in verdicts_sorted if v.get("phase") == "provisional"]

    fault_labels = [lbl for lbl in labels if not lbl.get("genuine_event", False)]

    # Determine station-days total
    stations_set = {v["station_id"] for v in final_verdicts}
    if final_verdicts:
        min_ts = _parse_ts(final_verdicts[0]["ts_utc"])
        max_ts = _parse_ts(final_verdicts[-1]["ts_utc"])
        span_days = max(1.0, (max_ts - min_ts).total_seconds() / 86400.0)
    else:
        span_days = 1.0
    total_station_days = len(stations_set) * span_days

    # Map final verdicts by station
    verdicts_by_station: dict[str, list[dict]] = {}
    for v in final_verdicts:
        verdicts_by_station.setdefault(v["station_id"], []).append(v)

    # 1. Event-wise Recall and Detection Delay
    class_events: dict[tuple[str, str], list[dict]] = {}
    for lbl in fault_labels:
        var = lbl.get("variable", "T")
        rc = lbl.get("root_cause", "unknown")
        class_events.setdefault((var, rc), []).append(lbl)

    per_class_metrics: dict[str, dict[str, Any]] = {}
    total_fault_events = len(fault_labels)
    total_detected_events = 0

    # Drift rate binning
    drift_bins = {
        "<0.03 °C/day": {"count": 0, "delays_days": []},
        "0.03–0.1 °C/day": {"count": 0, "delays_days": []},
        ">0.1 °C/day": {"count": 0, "delays_days": []},
    }

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
                    v_vars = v.get("vars", {})
                    var_info = v_vars.get(var, {})
                    is_anomaly = (var_info.get("label") == "anomaly") or (v.get("label") == "anomaly" and var == "T")

                    if is_anomaly:
                        if first_detection_ts is None:
                            first_detection_ts = v_dt
                        break

            if first_detection_ts is not None:
                detected_count += 1
                delay_sec = max(0.0, (first_detection_ts - start_dt).total_seconds())
                class_delays.append(delay_sec)

                # Collect drift delays
                if rc == "drift":
                    rate = ev.get("params", {}).get("rate", 0.05)  # C/day
                    delay_days = delay_sec / 86400.0
                    if rate < 0.03:
                        bin_k = "<0.03 °C/day"
                    elif rate <= 0.1:
                        bin_k = "0.03–0.1 °C/day"
                    else:
                        bin_k = ">0.1 °C/day"
                    drift_bins[bin_k]["count"] += 1
                    drift_bins[bin_k]["delays_days"].append(delay_days)

            elif rc == "drift":
                rate = ev.get("params", {}).get("rate", 0.05)
                bin_k = "<0.03 °C/day" if rate < 0.03 else ("0.03–0.1 °C/day" if rate <= 0.1 else ">0.1 °C/day")
                drift_bins[bin_k]["count"] += 1

        recall = detected_count / len(ev_list) if ev_list else 0.0
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

    # 2. Incidents & Precision calculation (Incidents split every 24h & gap)
    incidents = _split_into_incidents(final_verdicts, max_incident_hours=max_inc_hours, max_gap_hours=max_gap_hours)

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
                if max(inc_s, ev_s) <= min(inc_e, ev_e):
                    matched = True
                    break
        if matched:
            tp_incidents += 1
        else:
            fp_incidents += 1

    total_incidents = len(incidents)
    precision = tp_incidents / total_incidents if total_incidents > 0 else 0.0
    overall_recall = total_detected_events / total_fault_events if total_fault_events > 0 else 0.0
    f1_score = (2 * precision * overall_recall) / (precision + overall_recall) if (precision + overall_recall) > 0 else 0.0

    fa_incidents_per_100_st_days = (fp_incidents / total_station_days) * 100.0 if total_station_days > 0 else 0.0
    fa_incidents_per_st_day = fp_incidents / total_station_days if total_station_days > 0 else 0.0

    # 3. Genuine Events Evaluation
    genuine_events_report = []
    total_genuine_fa_incidents = 0
    total_genuine_st_days = 0.0

    for g_ev in genuine_events_list:
        ev_name = g_ev.get("name", g_ev.get("type", "genuine_event"))
        s_dt = _parse_ts(g_ev["start"])
        e_dt = _parse_ts(g_ev["end"])
        lat_min = g_ev.get("lat_min", -90.0)
        lat_max = g_ev.get("lat_max", 90.0)
        lon_min = g_ev.get("lon_min", -180.0)
        lon_max = g_ev.get("lon_max", 180.0)

        # Matching verdicts
        matching_verdicts = []
        for v in final_verdicts:
            v_dt = _parse_ts(v["ts_utc"])
            if s_dt <= v_dt <= e_dt:
                v_lat = v.get("lat", 25.0)
                v_lon = v.get("lon", 75.0)
                if lat_min <= v_lat <= lat_max and lon_min <= v_lon <= lon_max:
                    matching_verdicts.append(v)

        n_readings = len(matching_verdicts)
        ev_st_days = max(0.01, (e_dt - s_dt).total_seconds() / 86400.0)

        # Count false-alarm incidents during genuine event
        g_incidents = _split_into_incidents(matching_verdicts, max_incident_hours=max_inc_hours, max_gap_hours=max_gap_hours)
        # Check how many g_incidents are not overlapping fault injections
        g_fa_incidents = 0
        for inc in g_incidents:
            st = inc["station_id"]
            var = inc["variable"]
            inc_s = inc["start_dt"]
            inc_e = inc["end_dt"]
            is_fault = False
            for lbl in fault_labels:
                if lbl["station_id"] == st and (lbl.get("variable") in (var, "all")):
                    ev_s = _parse_ts(lbl["start_ts"])
                    ev_e = _parse_ts(lbl["end_ts"])
                    if max(inc_s, ev_s) <= min(inc_e, ev_e):
                        is_fault = True
                        break
            if not is_fault:
                g_fa_incidents += 1

        g_fa_per_100_st_days = (g_fa_incidents / ev_st_days) * 100.0

        # Share of readings labelled genuine_event == True
        gen_true_cnt = sum(1 for v in matching_verdicts if v.get("genuine_event", False))
        gen_true_share = gen_true_cnt / n_readings if n_readings > 0 else 0.0

        genuine_events_report.append({
            "name": ev_name,
            "station_days": ev_st_days,
            "false_alarm_incidents": g_fa_incidents,
            "fa_per_100_st_days": g_fa_per_100_st_days,
            "genuine_event_true_share": gen_true_share,
        })
        total_genuine_fa_incidents += g_fa_incidents
        total_genuine_st_days += ev_st_days

    overall_genuine_fa_per_100_st_days = (total_genuine_fa_incidents / total_genuine_st_days) * 100.0 if total_genuine_st_days > 0 else (
        (fp_incidents / total_station_days) * 100.0 if total_station_days > 0 else 0.0
    )

    # 4. Clean False-Alarm Rate
    clean_verdicts_count = 0
    clean_false_alarms = 0

    for v in final_verdicts:
        st = v["station_id"]
        v_dt = _parse_ts(v["ts_utc"])

        in_fault = any(lbl["station_id"] == st and _parse_ts(lbl["start_ts"]) <= v_dt <= _parse_ts(lbl["end_ts"]) for lbl in fault_labels)
        in_genuine = any(_parse_ts(g["start"]) <= v_dt <= _parse_ts(g["end"]) for g in genuine_events_list)

        if not in_fault and not in_genuine:
            clean_verdicts_count += 1
            if v.get("label") == "anomaly":
                clean_false_alarms += 1

    clean_far = clean_false_alarms / clean_verdicts_count if clean_verdicts_count > 0 else 0.0

    # 5. Headline metric: Recall at fixed alert budget
    within_budget = fa_incidents_per_st_day <= alert_budget
    recall_at_budget = overall_recall if within_budget else 0.0

    metrics_out: dict[str, Any] = {
        "summary": {
            "total_fault_events": total_fault_events,
            "detected_fault_events": total_detected_events,
            "event_recall": overall_recall,
            "incident_precision": precision,
            "f1_score": f1_score,
            "false_alarm_incidents": fp_incidents,
            "false_alarm_incidents_per_100_station_days": fa_incidents_per_100_st_days,
            "false_alarm_incidents_per_station_day": fa_incidents_per_st_day,
            "alert_budget": alert_budget,
            "recall_at_alert_budget": recall_at_budget,
            "clean_false_alarm_rate": clean_far,
            "genuine_event_fa_per_100_st_days": overall_genuine_fa_per_100_st_days,
        },
        "per_class": per_class_metrics,
        "genuine_events": genuine_events_report,
        "drift_table": drift_bins,
        "total_verdicts": len(verdicts),
        "total_labels": len(labels),
    }

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        (out_p / "metrics.json").write_text(json.dumps(metrics_out, indent=2), encoding="utf-8")

        md_lines = [
            "# SkyGuard Evaluation Metrics Report",
            "",
            "## Summary & Headline Metrics",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Total Fault Events | {total_fault_events} |",
            f"| Event-wise Recall | {overall_recall:.4f} |",
            f"| Incident-wise Precision | {precision:.4f} |",
            f"| **F1 Score** | **{f1_score:.4f}** |",
            f"| False Alarm Incidents / 100 station-days | {fa_incidents_per_100_st_days:.2f} |",
            f"| Recall @ Alert Budget ({alert_budget} FAs/st-day) | **{recall_at_budget:.4f}** |",
            f"| Clean False Alarm Rate | {clean_far:.4f} ({clean_false_alarms}/{clean_verdicts_count}) |",
            f"| Genuine Event FA / 100 station-days | {overall_genuine_fa_per_100_st_days:.2f} |",
            "",
            "## Per-Class Breakdown (Variable x Root Cause)",
            "",
            "| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |",
            "|---|---|---|---|---|---|",
        ]

        for cls_name, info in per_class_metrics.items():
            cnt = info["n_events"]
            det = info["detected"]
            rec_str = f"{det}/{cnt}" if cnt < 50 else f"{info['recall']:.2%}"
            p50_str = f"{info['delay_p50_sec']:.1f}" if info['delay_p50_sec'] is not None else "N/A"
            p90_str = f"{info['delay_p90_sec']:.1f}" if info['delay_p90_sec'] is not None else "N/A"
            md_lines.append(f"| {cls_name} | {cnt} | {det} | {rec_str} | {p50_str} | {p90_str} |")

        if genuine_events_report:
            md_lines.extend([
                "",
                "## Genuine Events Breakdown",
                "",
                "| Event | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share |",
                "|---|---|---|---|---|",
            ])
            for g in genuine_events_report:
                md_lines.append(
                    f"| {g['name']} | {g['station_days']:.1f} | {g['false_alarm_incidents']} | "
                    f"{g['fa_per_100_st_days']:.2f} | {g['genuine_event_true_share']:.1%} |"
                )

        md_lines.extend([
            "",
            "## Sensor Drift Detection Delay",
            "",
            "| Drift Rate Bin | Events | Median Delay (Days) |",
            "|---|---|---|",
        ])
        for bin_name, b_info in drift_bins.items():
            b_cnt = b_info["count"]
            d_list = b_info["delays_days"]
            med_d = f"{sorted(d_list)[len(d_list)//2]:.2f}" if d_list else "N/A"
            md_lines.append(f"| {bin_name} | {b_cnt} | {med_d} |")

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
