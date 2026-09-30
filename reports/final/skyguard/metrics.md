# SkyGuard Evaluation Metrics Report

## Summary & Headline Metrics

| Metric | Value |
|---|---|
| Total Fault Events | 21346 |
| Event-wise Recall | 0.1860 |
| Incident-wise Precision | 0.7007 |
| **F1 Score** | **0.2940** |
| False Alarm Incidents / 100 station-days | 2.68 |
| Recall @ Alert Budget (0.05 FAs/st-day) | **0.1860** |
| Clean False Alarm Rate | 0.0011 (1089/974431) |
| Clean Uncertain Rate | 0.0442 (43118/974431) |
| Genuine Event FA / 100 station-days | 2.08 |

## Per-Class Breakdown (Variable x Root Cause)

| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |
|---|---|---|---|---|---|
| P x offset | 551 | 114 | 20.69% | 10800.0 | 95400.0 |
| RH x out_of_range | 606 | 22 | 3.63% | 1800.0 | 12600.0 |
| T x noise | 890 | 588 | 66.07% | 3600.0 | 32400.0 |
| all x power | 1916 | 0 | 0.00% | N/A | N/A |
| T x frozen | 569 | 88 | 15.47% | 25200.0 | 54000.0 |
| all x timeshift | 1914 | 0 | 0.00% | N/A | N/A |
| P x spike | 622 | 286 | 45.98% | 0.0 | 1800.0 |
| RH x spike | 622 | 8 | 1.29% | 9000.0 | 54000.0 |
| T x spike | 623 | 608 | 97.59% | 0.0 | 1800.0 |
| P x frozen | 619 | 13 | 2.10% | 14400.0 | 77400.0 |
| T x radiation | 1750 | 58 | 3.31% | 10800.0 | 30600.0 |
| T x out_of_range | 568 | 558 | 98.24% | 0.0 | 0.0 |
| all x comms_gap | 1887 | 0 | 0.00% | N/A | N/A |
| RH x unknown | 786 | 62 | 7.89% | 30600.0 | 81000.0 |
| all x duplicate | 1883 | 0 | 0.00% | N/A | N/A |
| T x unknown | 876 | 380 | 43.38% | 19800.0 | 61200.0 |
| T x offset | 509 | 280 | 55.01% | 0.0 | 54000.0 |
| RH x frozen | 541 | 39 | 7.21% | 16200.0 | 68400.0 |
| RH x offset | 532 | 44 | 8.27% | 41400.0 | 102600.0 |
| P x out_of_range | 651 | 610 | 93.70% | 0.0 | 0.0 |
| RH x drift | 803 | 86 | 10.71% | 81000.0 | 196200.0 |
| T x drift | 739 | 81 | 10.96% | 91800.0 | 180000.0 |
| RH x noise | 889 | 46 | 5.17% | 12600.0 | 41400.0 |

## Genuine Events Breakdown

| Event | Stations in BBox | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share | Skipped (No Coords) |
|---|---|---|---|---|---|---|
| heatwave_nw_india_2024 | 95 | 760.0 | 22 | 2.89 | 0.0% | 0 |
| cyclone_remal_2024 | 44 | 176.0 | 0 | 0.00 | 0.0% | 0 |
| cyclone_fengal_2024 | 43 | 215.0 | 0 | 0.00 | 0.0% | 0 |
| fog_igp_jan_2024 | 84 | 1596.0 | 36 | 2.26 | 0.0% | 0 |
| cyclone_michaung_2023 | 7 | 42.0 | 0 | 0.00 | 0.0% | 0 |

## Sensor Drift Detection Delay

| Drift Rate Bin | Events | Median Delay (Days) |
|---|---|---|
| <0.03 °C/day | 0 | N/A |
| 0.03–0.1 °C/day | 1542 | 1.00 |
| >0.1 °C/day | 0 | N/A |
