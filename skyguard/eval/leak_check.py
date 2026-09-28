"""Leak check — fails loudly if forbidden fields reach model features.  Owner: Person B.

Uses :func:`skyguard.contract.assert_no_leak` and additionally checks that
injection metadata is never present in input rows.
"""
from __future__ import annotations


def check_no_leak(feature_names: list[str], rows: list[dict]) -> None:
    """Raise AssertionError if any forbidden field is in features or rows."""
    raise NotImplementedError
