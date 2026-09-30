# SkyGuard Evaluation Metrics Report

## Summary & Headline Metrics

| Metric | Value |
|---|---|
| Total Fault Events | 21346 |
| Event-wise Recall | 0.2117 |
| Incident-wise Precision | 0.1817 |
| **F1 Score** | **0.1956** |
| False Alarm Incidents / 100 station-days | 18.51 |
| Recall @ Alert Budget (0.05 FAs/st-day) | **0.0000** |
| Clean False Alarm Rate | 0.0357 (34752/974431) |
| Clean Uncertain Rate | 0.0000 (0/974431) |
| Genuine Event FA / 100 station-days | 143.89 |

## Per-Class Breakdown (Variable x Root Cause)

| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |
|---|---|---|---|---|---|
| P x offset | 551 | 262 | 47.55% | 3600.0 | 50400.0 |
| RH x out_of_range | 606 | 32 | 5.28% | 1800.0 | 32400.0 |
| T x noise | 890 | 503 | 56.52% | 3600.0 | 30600.0 |
| all x power | 1916 | 0 | 0.00% | N/A | N/A |
| T x frozen | 569 | 201 | 35.33% | 21600.0 | 54000.0 |
| all x timeshift | 1914 | 0 | 0.00% | N/A | N/A |
| P x spike | 622 | 344 | 55.31% | 0.0 | 3600.0 |
| RH x spike | 622 | 24 | 3.86% | 1800.0 | 32400.0 |
| T x spike | 623 | 606 | 97.27% | 0.0 | 1800.0 |
| P x frozen | 619 | 52 | 8.40% | 19800.0 | 57600.0 |
| T x radiation | 1750 | 256 | 14.63% | 5400.0 | 28800.0 |
| T x out_of_range | 568 | 558 | 98.24% | 0.0 | 0.0 |
| all x comms_gap | 1887 | 0 | 0.00% | N/A | N/A |
| RH x unknown | 786 | 87 | 11.07% | 16200.0 | 72000.0 |
| all x duplicate | 1883 | 0 | 0.00% | N/A | N/A |
| T x unknown | 876 | 289 | 32.99% | 14400.0 | 61200.0 |
| T x offset | 509 | 264 | 51.87% | 0.0 | 54000.0 |
| RH x frozen | 541 | 41 | 7.58% | 7200.0 | 50400.0 |
| RH x offset | 532 | 49 | 9.21% | 25200.0 | 117000.0 |
| P x out_of_range | 651 | 608 | 93.39% | 0.0 | 0.0 |
| RH x drift | 803 | 112 | 13.95% | 34200.0 | 171000.0 |
| T x drift | 739 | 173 | 23.41% | 41400.0 | 151200.0 |
| RH x noise | 889 | 59 | 6.64% | 10800.0 | 32400.0 |

## Genuine Events Breakdown

| Event | Stations in BBox | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share | Skipped (No Coords) |
|---|---|---|---|---|---|---|
| heatwave_nw_india_2024 | 95 | 760.0 | 2096 | 275.79 | 0.0% | 0 |
| cyclone_remal_2024 | 44 | 176.0 | 689 | 391.48 | 0.0% | 0 |
| cyclone_fengal_2024 | 43 | 215.0 | 595 | 276.74 | 0.0% | 0 |
| fog_igp_jan_2024 | 84 | 1596.0 | 633 | 39.66 | 0.0% | 0 |
| cyclone_michaung_2023 | 7 | 42.0 | 0 | 0.00 | 0.0% | 0 |

## Sensor Drift Detection Delay

| Drift Rate Bin | Events | Median Delay (Days) |
|---|---|---|
| <0.03 °C/day | 0 | N/A |
| 0.03–0.1 °C/day | 1542 | 0.42 |
| >0.1 °C/day | 0 | N/A |
