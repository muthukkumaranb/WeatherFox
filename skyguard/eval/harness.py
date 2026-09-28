"""Evaluation harness — event-wise metrics per variable × root cause.  Owner: Person B.

Measures precision, recall, F1, detection delay and genuine-event false-alarm
rate.  Fails loudly if ``qc`` or injection metadata reaches the features.
"""
from __future__ import annotations


def evaluate(
    verdicts: list[dict],
    labels: list[dict],
) -> dict:
    """Run the full evaluation suite.

    Returns a dict with per-variable, per-root-cause, and aggregate metrics.
    """
    raise NotImplementedError
