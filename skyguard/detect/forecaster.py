"""LightGBM forecaster on lags, climatology and neighbour features.  Owner: Person A.

Trained on NORMAL data only.  The anomaly signal is the residual.
"""
from __future__ import annotations


def train(train_rows: list[dict], *, seed: int = 42) -> object:
    """Train the forecaster.  Returns a model object."""
    raise NotImplementedError


def predict(model: object, features: dict[str, float]) -> dict[str, float]:
    """Return predicted T, RH, P from features."""
    raise NotImplementedError
