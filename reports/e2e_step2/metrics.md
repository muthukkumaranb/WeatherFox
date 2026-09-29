# SkyGuard Evaluation Metrics Report

## Summary & Headline Metrics

| Metric | Value |
|---|---|
| Total Fault Events | 2 |
| Event-wise Recall | 1.0000 |
| Incident-wise Precision | 0.6667 |
| **F1 Score** | **0.8000** |
| False Alarm Incidents / 100 station-days | 33.33 |
| Recall @ Alert Budget (0.05 FAs/st-day) | **0.0000** |
| Clean False Alarm Rate | 0.0000 (0/2) |
| Genuine Event FA / 100 station-days | 0.00 |

## Per-Class Breakdown (Variable x Root Cause)

| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |
|---|---|---|---|---|---|
| T x out_of_range | 1 | 1 | 1/1 | 900.0 | 900.0 |
| RH x frozen | 1 | 1 | 1/1 | 3600.0 | 3600.0 |

## Genuine Events Breakdown

| Event | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share |
|---|---|---|---|---|
| NW India Heat Wave May 2024 | 14.0 | 0 | 0.00 | 0.0% |

## Sensor Drift Detection Delay

| Drift Rate Bin | Events | Median Delay (Days) |
|---|---|---|
| <0.03 °C/day | 0 | N/A |
| 0.03–0.1 °C/day | 0 | N/A |
| >0.1 °C/day | 0 | N/A |
