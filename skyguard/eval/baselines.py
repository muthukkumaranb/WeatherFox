"""Baselines: rule-gate-only, z-score, Isolation Forest, HadISD flags.  Owner: Person B."""
from __future__ import annotations


def zscore_baseline(rows: list[dict]) -> list[dict]:
    """Simple z-score baseline detector.  Returns verdict-like dicts."""
    raise NotImplementedError


def isolation_forest_baseline(rows: list[dict]) -> list[dict]:
    """Isolation Forest baseline detector.  Returns verdict-like dicts."""
    raise NotImplementedError
