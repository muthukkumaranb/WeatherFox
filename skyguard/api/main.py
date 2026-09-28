"""FastAPI + WebSocket + /inject-fault endpoint.  Owner: Person B.

Serves verdicts in real-time and exposes the dashboard.
"""
from __future__ import annotations

from typing import Any
from ..scorer import score


def health_check() -> dict[str, str]:
    """GET /health endpoint handler."""
    return {"status": "ok", "version": "0.1.0"}


def score_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /score endpoint handler.

    Expects payload: {"station_window": dict, "target": str} or window dict.
    """
    station_window = payload.get("station_window", payload)
    target = payload.get("target")
    if not target and isinstance(station_window, dict):
        keys = [k for k in station_window.keys() if k not in ("target", "station_window", "rows")]
        if keys:
            target = keys[0]
    return score(station_window, target=target)


def create_app() -> object:
    """Create and return the FastAPI application instance."""
    try:
        from fastapi import FastAPI, Request
        app = FastAPI(title="SkyGuard AI API", version="0.1.0")

        @app.get("/health")
        def health():
            return health_check()

        @app.post("/score")
        async def score_api(request: Request):
            payload = await request.json()
            return score_endpoint(payload)

        return app
    except ImportError:
        raise NotImplementedError("FastAPI is not installed in the environment.")
