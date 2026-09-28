"""Climatology features (hour-of-day, day-of-year baselines).  Owner: Person A."""
from __future__ import annotations


def climatology_features(row: dict, history: list[dict]) -> dict[str, float]:
    """Return climatological baseline features for the given row."""
    raise NotImplementedError
