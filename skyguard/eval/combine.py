"""Combine harness metrics.json outputs from multiple arms into a single benchmark report. Owner: Person B."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def combine_arms(
    arms_input: dict[str, str | Path | dict],
    context: str,
    git_sha: str = "",
    split_sha256: str = "",
    out_path: str | Path = "reports/final/metrics.json",
) -> dict[str, Any]:
    """Combine per-arm metrics.json files into one unified metrics dict.

    Parameters
    ----------
    arms_input:
        Mapping of arm_name -> path to metrics.json file (or loaded dict).
    context:
        Required context string describing dataset/split.
    git_sha:
        Optional git SHA hash.
    split_sha256:
        Optional split SHA256 checksum.
    out_path:
        Output path for combined JSON metrics file.

    Returns
    -------
    dict
        Combined report dict.
    """
    arms_combined: dict[str, dict] = {}

    for arm_name, src in arms_input.items():
        if isinstance(src, (str, Path)):
            p = Path(src)
            if p.exists():
                arms_combined[arm_name] = json.loads(p.read_text(encoding="utf-8"))
            else:
                arms_combined[arm_name] = {}
        elif isinstance(src, dict):
            arms_combined[arm_name] = src

    combined: dict[str, Any] = {
        "context": context,
        "git_sha": git_sha,
        "split_sha256": split_sha256,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "arms": arms_combined,
    }

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    # Generate side-by-side markdown report (metrics.md)
    md_path = out_p.parent / "metrics.md"
    md_lines = [
        "# SkyGuard Evaluation — Arms Side-by-Side Comparison",
        "",
        f"**Context:** {context}",
        f"**Git SHA:** `{git_sha or 'N/A'}` | **Split SHA256:** `{split_sha256 or 'N/A'}`",
        "",
        "| Metric | " + " | ".join(arms_combined.keys()) + " |",
        "|---| " + " | ".join(["---"] * len(arms_combined)) + " |",
    ]

    metrics_rows = [
        ("Total Fault Events", lambda s: str(s.get("total_fault_events", "N/A"))),
        ("Event Recall", lambda s: f"{s.get('event_recall', 0.0):.4f}" if isinstance(s.get("event_recall"), (int, float)) else "N/A"),
        ("Incident Precision", lambda s: f"{s.get('incident_precision', 0.0):.4f}" if isinstance(s.get("incident_precision"), (int, float)) else "N/A"),
        ("F1 Score", lambda s: f"**{s.get('f1_score', 0.0):.4f}**" if isinstance(s.get("f1_score"), (int, float)) else "N/A"),
        ("Clean Anomaly Rate", lambda s: f"{s.get('clean_false_alarm_rate', 0.0):.4f}" if isinstance(s.get("clean_false_alarm_rate"), (int, float)) else "N/A"),
        ("Clean Uncertain Rate", lambda s: f"{s.get('clean_uncertain_rate', 0.0):.4f}" if isinstance(s.get("clean_uncertain_rate"), (int, float)) else "N/A"),
        ("Recall @ Alert Budget (<=0.05 FAs/st-day)", lambda s: f"{s.get('recall_at_alert_budget', 0.0):.4f}" if isinstance(s.get("recall_at_alert_budget"), (int, float)) else "N/A"),
        ("Genuine Event FA / 100 st-days", lambda s: f"{s.get('genuine_event_fa_per_100_st_days', 0.0):.2f}" if isinstance(s.get("genuine_event_fa_per_100_st_days"), (int, float)) else "N/A"),
    ]

    for label, extractor in metrics_rows:
        row_vals = []
        for arm_data in arms_combined.values():
            summary = arm_data.get("summary", arm_data)
            row_vals.append(extractor(summary))
        md_lines.append(f"| {label} | " + " | ".join(row_vals) + " |")

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine arm metrics into final metrics.json")
    parser.add_argument("--arm", action="append", required=True, help="Arm specification: name=path/to/metrics.json")
    parser.add_argument("--context", type=str, required=True, help="Evaluation context string")
    parser.add_argument("--git-sha", type=str, default="", help="Git SHA commit hash")
    parser.add_argument("--split-sha256", type=str, default="", help="Split SHA256 checksum")
    parser.add_argument("--out", type=str, default="reports/final/metrics.json", help="Output JSON file path")
    args = parser.parse_args()

    arms_map = {}
    for arm_str in args.arm:
        if "=" in arm_str:
            name, path_str = arm_str.split("=", 1)
            arms_map[name.strip()] = path_str.strip()
        else:
            raise ValueError(f"Invalid --arm argument format '{arm_str}'. Must be name=path")

    combine_arms(
        arms_map,
        context=args.context,
        git_sha=args.git_sha,
        split_sha256=args.split_sha256,
        out_path=args.out,
    )
    print(f"Combined {len(arms_map)} arms into {args.out}")


if __name__ == "__main__":
    main()
