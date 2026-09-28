"""Rule gate — fast pre-filter for obvious faults.  Owner: Person B.

Pure Python, no numpy.  Runs before the forecaster.  Decides ``duplicate``,
``timeshift`` and ``comms_gap`` at ingest (these are never passed to the
classifier).  Also flags obvious out-of-range and frozen values.

The frozen signature is:

    check(rows) -> {"T": {"flag": bool, "cause": str | None, "reason": str},
                    "RH": {...}, "P": {...}}
"""
from __future__ import annotations


def check(rows: list[dict]) -> dict[str, dict]:
    """Run rule-based checks on a short history of contract rows.

    Parameters
    ----------
    rows:
        Recent contract input-row dicts for ONE station, oldest → newest.

    Returns
    -------
    dict
        Per-variable results, each with keys ``flag`` (bool — True if a rule
        fired), ``cause`` (str | None — one of the contract root causes, or
        None when flag is False) and ``reason`` (str — human-readable).

        Example::

            {
                "T":  {"flag": False, "cause": None, "reason": "OK"},
                "RH": {"flag": True,  "cause": "out_of_range", "reason": "RH=130 > 100"},
                "P":  {"flag": False, "cause": None, "reason": "OK"},
            }
    """
    raise NotImplementedError
