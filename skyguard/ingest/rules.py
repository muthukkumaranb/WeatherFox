"""Ingest rules: duplicate, timeshift, comms_gap detection.  Owner: Person B.

These root causes are decided at ingest and never by the classifier.
"""
from __future__ import annotations


def detect_duplicate(rows: list[dict]) -> list[int]:
    """Return indices of duplicate rows."""
    raise NotImplementedError


def detect_timeshift(rows: list[dict], *, tolerance_min: int = 30) -> list[int]:
    """Return indices of rows with suspicious timestamp shifts."""
    raise NotImplementedError


def detect_comms_gap(rows: list[dict], *, cadence_min: int = 180) -> list[tuple[int, int]]:
    """Return (start_idx, end_idx) ranges where comms gaps are detected."""
    raise NotImplementedError
