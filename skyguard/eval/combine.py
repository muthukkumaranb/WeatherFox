import json
from pathlib import Path

def main():
    reports_dir = Path("reports") / "final"
    with open(reports_dir / "metrics.json") as f:
        metrics = json.load(f)
    
    # Just rewrite metrics.md to be sure it matches requirements
    git_sha = metrics.get("git_sha", "unknown")
    split_sha = metrics.get("split_sha256", "unknown")
    t_skyguard = metrics.get("total_runtime_s", 0)
    metrics_skyguard = metrics.get("skyguard", {})
    
    md = [
        "# Skyguard Final Test Metrics",
        f"**Git SHA**: `{git_sha}`",
        f"**Split SHA256**: `{split_sha}`",
        f"**Total Runtime (Batch)**: {t_skyguard:.1f}s",
        "",
        "## Clean Rates",
        f"- Clean Anomaly Rate: {metrics_skyguard.get('clean_anomaly_rate', 0)*100:.3f}%",
        f"- Clean Uncertain Rate: {metrics_skyguard.get('clean_uncertain_rate', 0)*100:.3f}%",
        "",
        "## False Alarms",
        f"- FA per station-day: {metrics_skyguard.get('fa_per_day', 0):.3f}",
        f"- Genuine-event FA per 100 station-days: {metrics_skyguard.get('genuine_fa_per_100_days', 0):.3f}",
        "",
        "## Event Recall",
        "| Root Cause | Detected | Total | Recall | Chance |",
        "|---|---|---|---|---|"
    ]
    
    for cause, d in sorted(metrics_skyguard.get("recall_by_cause", {}).items()):
        rec = d["detected"] / max(d["total"], 1)
        chance = metrics_skyguard.get('chance_recall', 0)
        md.append(f"| {cause} | {d['detected']} | {d['total']} | {rec*100:.1f}% | {chance*100:.1f}% |")
        
    with open(reports_dir / "metrics.md", "w") as f:
        f.write("\n".join(md))

if __name__ == '__main__':
    main()
