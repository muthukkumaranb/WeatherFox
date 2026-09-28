"""Replay engine — builds station_window and feeds score().  Owner: Person B.

Keeps rolling 24 h buffers per station.  The neighbour list comes from the
station registry, not from the input row.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Iterator


def load_replay_stream(source: str | Path | Iterable[dict]) -> Iterator[dict]:
    """Load a stream of contract input rows from a path or an iterable of dicts.

    If given an iterable of dicts, returns an iterator over it.
    If given a path (str or Path), reads the file (CSV or JSON lines) and yields row dicts.
    """
    if not isinstance(source, (str, Path)):
        return iter(source)
    path = Path(source)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield dict(row)
    else:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def replay(
    rows: list[dict],
    registry: dict[str, dict],
    *,
    scorer: object | None = None,
) -> list[dict]:
    """Replay a stream of rows through the detector.

    Returns a list of verdicts.  Uses :func:`skyguard.scorer.score` by
    default.
    """
    raise NotImplementedError
