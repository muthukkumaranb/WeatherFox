"""End-to-end detector — wires all detect components together.  Owner: Person A.

Pipeline order (per contract §7):
  rule gate → forecaster → neighbour check → event-protection → root-cause
  classifier → health/drift → imputation.
"""
from __future__ import annotations


def detect(station_window: dict[str, list[dict]], target: str) -> dict:
    """Run the full detection pipeline and return per-variable results.

    This is called by :func:`skyguard.verdict.api.score` to produce the
    raw detection signals that are then assembled into a verdict.
    """
    raise NotImplementedError
