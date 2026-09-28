"""Single swap point for the SkyGuard detector.

Every module (replay, API, demo, eval) imports ``score`` from here.
The actual implementation is chosen at call time by the environment variable
``SKYGUARD_SCORER``:

- ``"fake"`` (default): uses :func:`skyguard.fake_score.score`
- ``"real"``: lazily imports :func:`skyguard.verdict.api.score`

Any other value raises :class:`ValueError`.  The ``"real"`` backend raises a
clear error if the real detector is missing or only has stubs — it never
silently falls back to the fake.

Validation strategy (validate once):

- Rows are validated at ingest (replay/API) via :func:`contract.ingest_row`.
- Here we check only the window *structure* and the target's newest row
  via :func:`contract.check_window`.
- The returned verdict is validated with :func:`contract.validate_verdict`.
"""
from __future__ import annotations

import logging
import os

from .contract import check_window, validate_verdict

logger = logging.getLogger(__name__)


def score(station_window: dict[str, list[dict]], target: str) -> dict:
    """Score one reading.  ``target`` is required; no silent defaults.

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
        A validated verdict dict.
    """
    check_window(station_window, target)

    backend = os.environ.get("SKYGUARD_SCORER", "fake")

    if backend == "fake":
        from .fake_score import score as _score
    elif backend == "real":
        try:
            from .verdict.api import score as _score  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "SKYGUARD_SCORER='real' but skyguard.verdict.api could not be "
                f"imported: {exc}"
            ) from exc
    else:
        raise ValueError(
            f"SKYGUARD_SCORER must be 'fake' or 'real', got {backend!r}"
        )

    verdict = _score(station_window, target)
    return validate_verdict(verdict)
