"""Leak check — fails loudly if forbidden fields reach model features.  Owner: Person B.

Uses :data:`skyguard.contract.FORBIDDEN_FEATURES` and additionally checks that
injection metadata is never present in input rows or training splits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable, Union

from skyguard.contract import FORBIDDEN_FEATURES


def assert_no_forbidden(feature_names: Iterable[str]) -> None:
    """Raise AssertionError if any forbidden feature is present in feature_names."""
    forbidden = set(FORBIDDEN_FEATURES)
    found = []
    for feat in feature_names:
        if feat in forbidden:
            found.append(feat)
        else:
            for prefix in ("qc", "injection", "is_injected", "root_cause_true", "split", "label"):
                if feat.startswith(f"{prefix}_") or feat == prefix:
                    found.append(feat)
                    break
    if found:
        raise AssertionError(f"Forbidden feature(s) detected in feature_names: {found}")


def assert_no_split_leak(
    train_rows_or_path: Union[list[dict], str, Path],
    split_json_or_path: Union[dict, str, Path],
) -> None:
    """Check that training rows contain no test-period data and no unseen test stations."""
    # Load split info
    if isinstance(split_json_or_path, (str, Path)):
        split_path = Path(split_json_or_path)
        content = split_path.read_bytes()
        split_info = json.loads(content.decode("utf-8"))
        if "sha256" in split_info:
            expected_sha = split_info["sha256"]
            # verify SHA if checksum provided alongside
            actual_sha = hashlib.sha256(content).hexdigest()
            if expected_sha and actual_sha != expected_sha:
                raise AssertionError(f"split.json sha256 mismatch: expected {expected_sha}, got {actual_sha}")
    else:
        split_info = split_json_or_path

    test_start = split_info.get("test_start", "2024-01-01T00:00:00Z")
    test_unseen = set(split_info.get("test_unseen_stations", split_info.get("test_stations", [])))

    # Load train rows
    if isinstance(train_rows_or_path, (str, Path)):
        train_path = Path(train_rows_or_path)
        train_rows = []
        with train_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    train_rows.append(json.loads(line))
    else:
        train_rows = train_rows_or_path

    leaks = []
    for idx, row in enumerate(train_rows):
        st = row.get("station_id")
        ts = row.get("ts_utc", "")
        split_val = row.get("split")

        if split_val == "test":
            leaks.append(f"Row {idx} explicitly marked as split='test'")
        if st and st in test_unseen:
            leaks.append(f"Row {idx} station '{st}' is in unseen test stations set")
        if ts and ts >= test_start:
            leaks.append(f"Row {idx} timestamp '{ts}' is >= test_start '{test_start}'")

    if leaks:
        sample = leaks[:5]
        raise AssertionError(f"Split leak detected! {len(leaks)} violating row(s):\n  - " + "\n  - ".join(sample))


def check_no_leak(feature_names: list[str], rows: list[dict]) -> None:
    """Raise AssertionError if any forbidden field is in features or rows."""
    assert_no_forbidden(feature_names)
    forbidden_row_keys = {"qc", "injection_id", "is_injected", "root_cause_true"}
    for idx, r in enumerate(rows):
        present = forbidden_row_keys.intersection(r.keys())
        if present:
            raise AssertionError(f"Row {idx} contains forbidden input fields: {present}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check feature and dataset leak rules")
    parser.add_argument("--features", type=str, help="Comma-separated feature names")
    parser.add_argument("--train", type=str, help="Path to train dataset JSONL")
    parser.add_argument("--split", type=str, help="Path to split.json file")
    args = parser.parse_args()

    if args.features:
        feat_list = [f.strip() for f in args.features.split(",") if f.strip()]
        assert_no_forbidden(feat_list)
        print("✅ Feature leak check passed: no forbidden features.")

    if args.train and args.split:
        assert_no_split_leak(args.train, args.split)
        print("✅ Split leak check passed: no test leakage in training set.")


if __name__ == "__main__":
    main()
