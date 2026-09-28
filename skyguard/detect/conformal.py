"""Conformal calibration — rolling thresholds per cadence group.  Owner: Person A.

Calibrated on a validation slice (never the test set).
Two thresholds from config/skyguard.toml [conformal]:
  alpha_anomaly   = 0.001  (label → anomaly if p < alpha_anomaly)
  alpha_uncertain = 0.01   (label → uncertain if p < alpha_uncertain)
"""
from __future__ import annotations


def calibrate(
    val_residuals: list[float],
    *,
    alpha_anomaly: float = 0.001,
    alpha_uncertain: float = 0.01,
) -> dict[str, float]:
    """Return conformal thresholds at the two significance levels."""
    raise NotImplementedError


def p_value(residual: float, threshold: float) -> float:
    """Conformal p-value for a single residual given the calibrated threshold."""
    raise NotImplementedError
