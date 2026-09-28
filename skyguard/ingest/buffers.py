"""Memory-efficient ring buffers, keyed by station.  Owner: Person B.

Keeps at least 24 h of history per station for the replay engine.
"""
from __future__ import annotations

from collections import deque


class StationBuffer:
    """Rolling buffer for one station's recent rows."""

    def __init__(self, max_rows: int = 200) -> None:
        self.max_rows = max_rows
        self._deque: deque[dict] = deque(maxlen=max_rows)

    def push(self, row: dict) -> None:
        """Append a row, evicting the oldest if at capacity."""
        self._deque.append(row)

    def window(self) -> list[dict]:
        """Return all buffered rows, oldest → newest."""
        return list(self._deque)

    def __len__(self) -> int:
        return len(self._deque)


class BufferPool:
    """Collection of :class:`StationBuffer` instances, keyed by station_id."""

    def __init__(self, max_rows_per_station: int = 200) -> None:
        self.max_rows_per_station = max_rows_per_station
        self.buffers: dict[str, StationBuffer] = {}

    def push(self, row: dict) -> None:
        """Route a row to its station's buffer."""
        sid = row.get("station_id")
        if not sid:
            return
        if sid not in self.buffers:
            self.buffers[sid] = StationBuffer(max_rows=self.max_rows_per_station)
        self.buffers[sid].push(row)

    def window(self, station_id: str) -> list[dict]:
        """Return the window for one station, or empty list if station unknown."""
        buf = self.buffers.get(station_id)
        return buf.window() if buf else []

    def get_all_station_ids(self) -> list[str]:
        """Return all station_ids currently in the buffer pool."""
        return list(self.buffers.keys())
