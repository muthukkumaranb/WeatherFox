"""De-duplicate, time-grid snap and cadence assignment.  Owner: Person A.

Rules:
- De-duplicate METAR/SYNOP at the same timestamp (keep synoptic).
- Snap to a common time grid with ~30 min tolerance.
- Never reuse one neighbour report for two time slots.
"""
from __future__ import annotations


def dedup_metar_synop(rows: list[dict]) -> list[dict]:
    """Remove METAR duplicates when a SYNOP exists at the same timestamp."""
    raise NotImplementedError


def snap_to_grid(rows: list[dict], tolerance_min: int = 30) -> list[dict]:
    """Snap rows to a regular time grid within *tolerance_min* minutes."""
    raise NotImplementedError


def assign_cadence(rows: list[dict]) -> list[dict]:
    """Compute and assign ``cadence_min`` for each station's rows."""
    raise NotImplementedError
