"""Mark genuine-event windows (heat wave, fog, cyclone).  Owner: Person A.

Used by the injector to avoid injecting faults on top of genuine events,
and by the eval harness to measure the false-alarm rate on real extremes.
"""
from __future__ import annotations


def mark_genuine_events(rows: list[dict], registry: dict[str, dict]) -> list[dict]:
    """Annotate rows that fall inside a genuine-event window.

    Returns a list of event descriptors (station, variable, start, end, type).
    """
    raise NotImplementedError
