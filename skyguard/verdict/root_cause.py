"""Root-cause classifier on residual features.  Owner: Person A.

Trained on residual features plus injected faults.  Never sees injection
metadata or upstream QC codes.
"""
from __future__ import annotations


def classify(features: dict[str, float]) -> tuple[str, float]:
    """Return (root_cause, confidence) for the given feature dict."""
    raise NotImplementedError
