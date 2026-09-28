"""Neighbour comparison: median/IQR, rounding tolerance.  Owner: Person A.

Tolerates ~±1 °C for METAR rounding.  With no usable neighbours, outputs
``no_neighbours`` and reduces confidence.
"""
from __future__ import annotations


def neighbour_residuals(
    target_row: dict,
    neighbour_rows: dict[str, list[dict]],
) -> dict[str, float]:
    """Compute residuals between target and neighbour medians for T, RH, P."""
    raise NotImplementedError
