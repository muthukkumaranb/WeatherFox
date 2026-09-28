"""Hash-based station split.  Owner: Person A.

Split rule (deterministic by hash of station_id with a fixed salt):

    Three DISJOINT station groups:
      - train stations (~70%)       → year 2023 only
      - validation stations (15%)   → year 2023 only (held-out stations)
      - test = ALL stations in 2024 (time hold-out)
               PLUS the 15% unseen test stations in 2023 (station hold-out)

    The test split is locked and never tuned on.  Config lives in
    ``config/skyguard.toml`` under ``[split]``.
"""
from __future__ import annotations


def assign_split(station_id: str, ts_utc: str) -> str:
    """Return 'train', 'val' or 'test' for a given station and timestamp."""
    raise NotImplementedError


def split_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """Partition rows into {'train': [...], 'val': [...], 'test': [...]}."""
    raise NotImplementedError
