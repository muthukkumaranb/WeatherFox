"""SkyGuard contract: vocabularies, schema validation, cross-field rules, leak guards.

Every track (data/ML, backend, frontend, harness) imports from here so the
format is checked in one place.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

SCHEMA_VERSION = "1.0"
P_TYPES = ("slp", "altimeter", "station")
SOURCES = ("ghcnh_synop", "ghcnh_metar", "ghcnh_speci", "asos1min", "esp32")

# Ascending severity: the overall label of a verdict is the worst of its variables.
LABELS = ("normal", "uncertain", "anomaly")
ROOT_CAUSES = (
    "spike", "frozen", "drift", "offset", "noise", "out_of_range",
    "radiation", "power", "comms_gap", "duplicate", "timeshift", "unknown",
)
# Decided by rules at ingest, not by the classifier.
INGEST_CLASSES = ("duplicate", "timeshift", "comms_gap")
SPATIAL_SUPPORT = ("neighbours_normal", "neighbours_also_deviating", "no_neighbours")
VARIABLES = ("T", "RH", "P")

# Fields the detector must never use as features.
FORBIDDEN_FEATURES = frozenset({
    "qc", "injection_id", "is_injected", "root_cause_true", "split", "label",
})


class ContractError(ValueError):
    """Raised when a record violates the contract. Lists every problem found."""

    def __init__(self, kind: str, errors: list[str]):
        self.kind = kind
        self.errors = errors
        super().__init__(f"{kind} invalid:\n  - " + "\n  - ".join(errors))


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / name).read_text())
    return Draft202012Validator(schema)


_INPUT = _validator("input_row.schema.json")
_VERDICT = _validator("verdict.schema.json")
_INJECTION = _validator("injection_label.schema.json")


def _schema_errors(v: Draft202012Validator, obj: dict) -> list[str]:
    out = []
    for e in sorted(v.iter_errors(obj), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{path}: {e.message}")
    return out


def worst_label(labels: Iterable[str]) -> str:
    """Overall label rule: anomaly > uncertain > normal."""
    labels = list(labels)
    if not labels:
        raise ValueError("no labels")
    return max(labels, key=LABELS.index)


def validate_input_row(row: dict) -> dict:
    errs = _schema_errors(_INPUT, row)
    if errs:
        raise ContractError("input row", errs)
    return row


def validate_window(station_window: dict, target: str) -> str:
    """Validate a detector input: {station_id: [contract rows, oldest -> newest]}.

    *target* is required and must be a key of *station_window* with at least one row.
    Returns the validated target station id.
    """
    if not station_window:
        raise ContractError("station window", ["window is empty"])
    errs: list[str] = []
    if target not in station_window:
        errs.append(f"target station '{target}' is not a key in station_window")
    elif not station_window[target]:
        errs.append(f"target station '{target}' has no rows")
    for sid, rows in station_window.items():
        for i, row in enumerate(rows):
            for e in _schema_errors(_INPUT, row):
                errs.append(f"{sid}[{i}] {e}")
            if row.get("station_id") != sid:
                errs.append(f"{sid}[{i}]: station_id '{row.get('station_id')}' does not match window key")
    if errs:
        raise ContractError("station window", errs)
    return target


def validate_injection(label: dict) -> dict:
    errs = _schema_errors(_INJECTION, label)
    if not errs and label["end_ts"] < label["start_ts"]:
        errs.append("end_ts is before start_ts")
    if errs:
        raise ContractError("injection label", errs)
    return label


def validate_verdict(v: dict) -> dict:
    errs = _schema_errors(_VERDICT, v)
    if not errs:
        var_labels = [x["label"] for x in v["vars"].values()]
        if v["label"] != worst_label(var_labels):
            errs.append(f"label '{v['label']}' must equal the worst variable label '{worst_label(var_labels)}'")
        if v["genuine_event"] and not (
            v["label"] == "normal" and v["spatial_support"] == "neighbours_also_deviating"
        ):
            errs.append("genuine_event=true requires label=normal and spatial_support=neighbours_also_deviating")
        if v["spatial_support"] == "no_neighbours" and v["n_neighbours"] != 0:
            errs.append("spatial_support=no_neighbours requires n_neighbours=0")
        for var, h in v.get("health", {}).items():
            if h["trend"] == "insufficient_history" and h["ttm_days"] is not None:
                errs.append(f"health.{var}: ttm_days must be null when trend=insufficient_history")
    if errs:
        raise ContractError("verdict", errs)
    return v


def to_model_input(row: dict) -> dict:
    """Strip fields the detector must not see (upstream QC codes). Use in ONE place in the pipeline."""
    return {k: val for k, val in row.items() if k not in FORBIDDEN_FEATURES}


def assert_no_leak(feature_names: Iterable[str]) -> None:
    """Call on the model's feature list. Fails loudly if a forbidden field got in."""
    bad = sorted(set(feature_names) & FORBIDDEN_FEATURES)
    if bad:
        raise AssertionError(f"forbidden fields in model features: {bad}")
