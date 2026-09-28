"""Scalability test — latency and throughput measurement.  Owner: Person B."""
from __future__ import annotations


def measure_throughput(
    rows: list[dict],
    registry: dict[str, dict],
    *,
    n_stations: int = 100,
) -> dict:
    """Measure latency per reading and throughput for *n_stations*."""
    raise NotImplementedError
