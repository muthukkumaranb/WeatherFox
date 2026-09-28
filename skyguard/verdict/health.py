"""Sensor health tracking — CUSUM drift, score, trend, ttm_days.  Owner: Person A.

``ttm_days`` is null when ``trend`` is ``insufficient_history``.
"""
from __future__ import annotations


def update_health(
    variable: str,
    residuals: list[float],
    *,
    current_score: float | None = None,
) -> dict:
    """Return a health dict {score, trend, ttm_days}."""
    raise NotImplementedError
