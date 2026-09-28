"""Real detector entry point — same interface as fake_score.  Owner: Person A.

Called by :mod:`skyguard.scorer` when ``SKYGUARD_SCORER=real``.
"""
from __future__ import annotations


def score(station_window: dict[str, list[dict]], target: str) -> dict:
    """Score one reading using the real detection pipeline.

    Parameters
    ----------
    station_window:
        ``{station_id: [contract row dicts, oldest → newest]}`` for the
        target AND its neighbours.
    target:
        Station to judge.  Must be a key of *station_window*.

    Returns
    -------
    dict
        A verdict dict (validated by the caller in :mod:`skyguard.scorer`).
    """
    raise NotImplementedError("Real detector not implemented yet — use SKYGUARD_SCORER=fake")
