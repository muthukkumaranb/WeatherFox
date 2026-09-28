"""Assemble a full verdict dict from per-variable results.  Owner: Person A.

Overall ``label`` = worst variable label.  ``genuine_event`` only with
``label: normal`` and ``spatial_support: neighbours_also_deviating``.
"""
from __future__ import annotations


def assemble_verdict(
    station_id: str,
    ts_utc: str,
    var_results: dict[str, dict],
    *,
    n_neighbours: int,
    spatial_support: str,
    genuine_event: bool,
    phase: str = "final",
    model_version: str = "real-0.1",
    health: dict[str, dict] | None = None,
) -> dict:
    """Build a contract-valid verdict dict from per-variable sub-results."""
    raise NotImplementedError
