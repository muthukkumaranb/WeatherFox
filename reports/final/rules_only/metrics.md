# SkyGuard Evaluation Metrics Report

## Summary & Headline Metrics

| Metric | Value |
|---|---|
| Total Fault Events | 21346 |
| Event-wise Recall | 0.1486 |
| Incident-wise Precision | 0.5425 |
| **F1 Score** | **0.2333** |
| False Alarm Incidents / 100 station-days | 1.96 |
| Recall @ Alert Budget (0.05 FAs/st-day) | **0.1486** |
| Clean False Alarm Rate | 0.0001 (86/974431) |
| Clean Uncertain Rate | 0.0037 (3631/974431) |
| Genuine Event FA / 100 station-days | 0.07 |

## Per-Class Breakdown (Variable x Root Cause)

| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |
|---|---|---|---|---|---|
| P x offset | 551 | 0 | 0.00% | N/A | N/A |
| RH x out_of_range | 606 | 14 | 2.31% | 1800.0 | 10800.0 |
| T x noise | 890 | 521 | 58.54% | 5400.0 | 32400.0 |
| all x power | 1916 | 0 | 0.00% | N/A | N/A |
| T x frozen | 569 | 60 | 10.54% | 18000.0 | 54000.0 |
| all x timeshift | 1914 | 0 | 0.00% | N/A | N/A |
| P x spike | 622 | 0 | 0.00% | N/A | N/A |
| RH x spike | 622 | 6 | 0.96% | 9000.0 | 54000.0 |
| T x spike | 623 | 588 | 94.38% | 0.0 | 5400.0 |
| P x frozen | 619 | 0 | 0.00% | N/A | N/A |
| T x radiation | 1750 | 17 | 0.97% | 12600.0 | 32400.0 |
| T x out_of_range | 568 | 558 | 98.24% | 0.0 | 0.0 |
| all x comms_gap | 1887 | 0 | 0.00% | N/A | N/A |
| RH x unknown | 786 | 44 | 5.60% | 32400.0 | 81000.0 |
| all x duplicate | 1883 | 0 | 0.00% | N/A | N/A |
| T x unknown | 876 | 347 | 39.61% | 21600.0 | 61200.0 |
| T x offset | 509 | 229 | 44.99% | 0.0 | 54000.0 |
| RH x frozen | 541 | 26 | 4.81% | 10800.0 | 55800.0 |
| RH x offset | 532 | 30 | 5.64% | 57600.0 | 124200.0 |
| P x out_of_range | 651 | 608 | 93.39% | 0.0 | 0.0 |
| RH x drift | 803 | 54 | 6.72% | 79200.0 | 180000.0 |
| T x drift | 739 | 35 | 4.74% | 120600.0 | 208800.0 |
| RH x noise | 889 | 35 | 3.94% | 12600.0 | 30600.0 |

## Genuine Events Breakdown

| Event | Stations in BBox | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share | Skipped (No Coords) |
|---|---|---|---|---|---|---|
| heatwave_nw_india_2024 | 95 | 760.0 | 0 | 0.00 | 0.0% | 0 |
| cyclone_remal_2024 | 44 | 176.0 | 0 | 0.00 | 0.0% | 0 |
| cyclone_fengal_2024 | 43 | 215.0 | 0 | 0.00 | 0.0% | 0 |
| fog_igp_jan_2024 | 84 | 1596.0 | 2 | 0.13 | 0.0% | 0 |
| cyclone_michaung_2023 | 7 | 42.0 | 0 | 0.00 | 0.0% | 0 |

## Sensor Drift Detection Delay

| Drift Rate Bin | Events | Median Delay (Days) |
|---|---|---|
| <0.03 °C/day | 0 | N/A |
| 0.03–0.1 °C/day | 1542 | 1.10 |
| >0.1 °C/day | 0 | N/A |
