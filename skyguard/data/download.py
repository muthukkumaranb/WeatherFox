"""Download GHCNh hourly data for Indian stations.  Owner: Person A.

Fetches from NCEI/NOAA, filters to Indian stations with ≥ 2 500 reports/yr,
and converts raw records to contract input rows.
"""
from __future__ import annotations


def download_ghcnh(dest_dir: str, *, years: tuple[int, ...] = (2023, 2024)) -> None:
    """Download GHCNh hourly files for Indian stations."""
    raise NotImplementedError


def parse_to_rows(raw_path: str) -> list[dict]:
    """Parse a raw GHCNh file into contract input-row dicts."""
    raise NotImplementedError
