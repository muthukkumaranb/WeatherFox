"""Fault injector — all 12 root-cause classes.  Owner: Person A.

Randomises magnitude, duration and rate.  Writes the injection-label file
separately (never adds labels to input rows).
"""
from __future__ import annotations


def inject_faults(
    rows: list[dict],
    *,
    seed: int = 42,
    rate: float = 0.05,
) -> tuple[list[dict], list[dict]]:
    """Inject faults into *rows*.

    Returns (modified_rows, injection_labels).  The labels are contract-valid
    injection-label dicts written to a separate file.
    """
    raise NotImplementedError
