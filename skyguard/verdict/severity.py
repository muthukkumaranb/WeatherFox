"""Severity scoring — map residuals to severity and severity_score.  Owner: Person A."""
from __future__ import annotations


def compute_severity(
    root_cause: str,
    residual: float,
    confidence: float,
) -> tuple[str, int]:
    """Return (severity, severity_score) for one variable verdict."""
    raise NotImplementedError
