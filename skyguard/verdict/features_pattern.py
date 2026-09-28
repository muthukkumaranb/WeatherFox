"""Pattern-based features for the root-cause classifier.  Owner: Person A."""
from __future__ import annotations


def extract_features(
    row: dict,
    history: list[dict],
    residuals: dict[str, float],
) -> dict[str, float]:
    """Build the feature dict that feeds the root-cause classifier."""
    raise NotImplementedError
