"""Conformal calibration — rolling thresholds per cadence group.  Owner: Person A.

Calibrated on a validation slice (never the test set).
"""
from __future__ import annotations


def calibrate(val_residuals: list[float], *, alpha: float = 0.05) -> float:
    """Return the conformal threshold at significance level *alpha*."""
    raise NotImplementedError


def p_value(residual: float, threshold: float) -> float:
    """Conformal p-value for a single residual given the calibrated threshold."""
    raise NotImplementedError
