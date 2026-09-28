"""Export cleaned data as a contract-row stream for replay.  Owner: Person A."""
from __future__ import annotations


def stream_rows(data_dir: str, *, station_ids: list[str] | None = None) -> list[dict]:
    """Yield contract input-row dicts in chronological order."""
    raise NotImplementedError
