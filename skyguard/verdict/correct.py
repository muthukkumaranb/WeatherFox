"""Corrected value — blend of forecaster and neighbour predictions.  Owner: Person A.

Always provides ``sigma`` and ``method``.
"""
from __future__ import annotations


def correct(
    variable: str,
    forecast: float,
    neighbour_median: float | None,
    *,
    forecast_sigma: float,
    neighbour_sigma: float | None,
) -> dict:
    """Return a corrected-value dict {value, sigma, method}."""
    raise NotImplementedError
