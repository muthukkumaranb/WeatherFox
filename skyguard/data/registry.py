"""Station registry: metadata and neighbour lookup.  Owner: Person A.

Holds lat, lon, elevation for every station.  The replay engine and detector
use this to find neighbours — the neighbour list is NEVER in the input row.
"""
from __future__ import annotations


def load_registry(path: str) -> dict[str, dict]:
    """Load station metadata keyed by station_id."""
    raise NotImplementedError


def neighbours(station_id: str, registry: dict[str, dict], *, max_km: float = 200.0) -> list[str]:
    """Return station_ids of neighbours within *max_km* km, sorted by distance."""
    raise NotImplementedError
