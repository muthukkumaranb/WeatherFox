"""Replay engine — builds station_window and feeds score().  Owner: Person B.

Keeps rolling 24 h buffers per station.  The neighbour list comes from the
station registry, not from the input row.
"""
from __future__ import annotations


def replay(
    rows: list[dict],
    registry: dict[str, dict],
    *,
    scorer: object | None = None,
) -> list[dict]:
    """Replay a stream of rows through the detector.

    Returns a list of verdicts.  Uses :func:`skyguard.scorer.score` by
    default.
    """
    raise NotImplementedError
