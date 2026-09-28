"""TreeSHAP → reasons[] and action strings.  Owner: Person A.

Turns SHAP values into plain-language ``reasons[].text`` and an ``action``.
"""
from __future__ import annotations


def shap_reasons(
    features: dict[str, float],
    model: object,
) -> list[dict]:
    """Return a list of reason dicts (feature, value, contribution, text)."""
    raise NotImplementedError


def suggest_action(root_cause: str, severity: str) -> str:
    """Map root_cause + severity to a human-readable action string."""
    raise NotImplementedError
