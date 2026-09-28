"""Event-protection rule.  Owner: Person A.

If the station and enough neighbours deviate in the same direction it is a
regional event, not a fault.  A lone deviation with calm neighbours is a fault.
Never suppress genuine extremes.
"""
from __future__ import annotations


def is_genuine_event(
    target_resid: dict[str, float],
    neighbour_resids: dict[str, dict[str, float]],
) -> bool:
    """Return True if the deviation looks like a genuine regional event."""
    raise NotImplementedError
