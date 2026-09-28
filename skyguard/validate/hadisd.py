"""HadISD silver-label comparison.  Owner: Person A.

India HadISD data up to Aug 2025 used for external validation.
"""
from __future__ import annotations


def load_hadisd_flags(path: str) -> dict[str, list[dict]]:
    """Load HadISD quality flags for Indian stations."""
    raise NotImplementedError


def compare_with_verdicts(
    verdicts: list[dict],
    hadisd_flags: dict[str, list[dict]],
) -> dict:
    """Compare SkyGuard verdicts against HadISD flags.  Returns agreement stats."""
    raise NotImplementedError
