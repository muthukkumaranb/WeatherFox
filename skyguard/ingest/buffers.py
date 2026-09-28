"""Memory-efficient ring buffers, keyed by station.  Owner: Person B.

Keeps at least 24 h of history per station for the replay engine.
"""
from __future__ import annotations


class StationBuffer:
    """Rolling buffer for one station's recent rows."""

    def __init__(self, max_rows: int = 200) -> None:
        raise NotImplementedError

    def push(self, row: dict) -> None:
        """Append a row, evicting the oldest if at capacity."""
        raise NotImplementedError

    def window(self) -> list[dict]:
        """Return all buffered rows, oldest → newest."""
        raise NotImplementedError


class BufferPool:
    """Collection of :class:`StationBuffer` instances, keyed by station_id."""

    def __init__(self, max_rows_per_station: int = 200) -> None:
        raise NotImplementedError

    def push(self, row: dict) -> None:
        """Route a row to its station's buffer."""
        raise NotImplementedError

    def window(self, station_id: str) -> list[dict]:
        """Return the window for one station."""
        raise NotImplementedError
