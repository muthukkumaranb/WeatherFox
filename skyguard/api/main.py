"""FastAPI + WebSocket + /inject-fault endpoint.  Owner: Person B.

Serves verdicts in real-time, manages replay control, fault injection,
sensor health board, and exposes dashboard APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..contract import validate_verdict
from ..ingest.replay import (
    build_synthetic_registry, generate_synthetic_stream, replay,
)
from ..scorer import score

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


class StateManager:
    """In-memory state manager for live replay, websocket clients, and APIs."""

    def __init__(self) -> None:
        self.registry: dict[str, dict] = build_synthetic_registry()
        self.verdicts: deque[dict] = deque(maxlen=2000)
        self.raw_rows: dict[str, deque[dict]] = {}
        self.active_websockets: list[WebSocket] = []
        self.speed_factor: float = 0.0
        self.active_injections: list[dict] = []
        self.lock = asyncio.Lock()

    def get_latest_verdict_per_station(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for v in self.verdicts:
            sid = v.get("station_id")
            if sid:
                latest[sid] = v
        return latest

    def add_verdict(self, verdict: dict) -> None:
        self.verdicts.append(verdict)

    def add_raw_row(self, row: dict) -> None:
        sid = row.get("station_id")
        if sid:
            if sid not in self.raw_rows:
                self.raw_rows[sid] = deque(maxlen=200)
            self.raw_rows[sid].append(row)


state = StateManager()


def apply_injections(row: dict) -> dict:
    """Apply active fault injections to an incoming input row."""
    if not state.active_injections:
        return row

    row_copy = dict(row)
    sid = row_copy.get("station_id")
    now_ts = row_copy.get("ts_utc", "")

    remaining_injections = []
    for inj in state.active_injections:
        if inj["station_id"] == sid:
            var = inj["variable"]
            cause = inj["root_cause"]
            mag = inj["magnitude"]

            if cause == "spike":
                row_copy[var] = mag
            elif cause == "frozen":
                row_copy[var] = mag
            elif cause == "offset":
                val = row_copy.get(var)
                if val is not None:
                    row_copy[var] = round(val + mag, 2)
            elif cause == "out_of_range":
                row_copy[var] = mag

            inj["count"] -= 1
            if inj["count"] > 0:
                remaining_injections.append(inj)
        else:
            remaining_injections.append(inj)

    state.active_injections = remaining_injections
    return row_copy


def health_check() -> dict[str, str]:
    """GET /health endpoint handler."""
    return {"status": "ok", "version": "0.1.0"}


def score_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /score endpoint handler."""
    station_window = payload.get("station_window", payload)
    target = payload.get("target")
    if not target and isinstance(station_window, dict):
        keys = [k for k in station_window.keys() if k not in ("target", "station_window", "rows")]
        if keys:
            target = keys[0]
    return score(station_window, target=target)


def create_app() -> FastAPI:
    """Create and return the FastAPI application instance."""
    app = FastAPI(title="SkyGuard AI API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return health_check()

    @app.post("/score")
    async def score_api(request: Request):
        payload = await request.json()
        return score_endpoint(payload)

    @app.get("/stations")
    def get_stations():
        latest_verdicts = state.get_latest_verdict_per_station()
        stations = []
        for sid, meta in state.registry.items():
            lv = latest_verdicts.get(sid, {})
            stations.append({
                "id": sid,
                "name": f"AWS {sid}",
                "lat": meta["lat"],
                "lon": meta["lon"],
                "elevation": meta.get("elevation", 0.0),
                "latest_label": lv.get("label", "normal"),
                "latest_ts": lv.get("ts_utc", None),
            })
        return stations

    @app.get("/stations/{station_id}/series")
    def get_station_series(station_id: str, hours: float = 48.0):
        raw = list(state.raw_rows.get(station_id, []))
        station_verdicts = [v for v in state.verdicts if v.get("station_id") == station_id]

        series = []
        verdict_by_ts = {v["ts_utc"]: v for v in station_verdicts}

        for r in raw:
            ts = r["ts_utc"]
            v = verdict_by_ts.get(ts, {})
            vars_v = v.get("vars", {})

            item = {
                "ts_utc": ts,
                "T": r.get("T"),
                "RH": r.get("RH"),
                "P": r.get("P"),
                "label": v.get("label", "normal"),
                "corrected_T": vars_v.get("T", {}).get("corrected", {}).get("value"),
                "corrected_RH": vars_v.get("RH", {}).get("corrected", {}).get("value"),
                "corrected_P": vars_v.get("P", {}).get("corrected", {}).get("value"),
            }
            series.append(item)
        return {"station_id": station_id, "hours": hours, "series": series}

    @app.get("/alerts")
    def get_alerts(since: str | None = None):
        alerts = []
        for v in reversed(state.verdicts):
            if v.get("label") in ("anomaly", "uncertain"):
                if since and v.get("ts_utc", "") < since:
                    continue
                alerts.append(v)
        return alerts

    @app.get("/health/sensors")
    def get_sensor_health():
        sensor_health = []
        latest = state.get_latest_verdict_per_station()
        for sid, v in latest.items():
            h_data = v.get("health", {})
            for var in ("T", "RH", "P"):
                h_var = h_data.get(var, {
                    "score": 0.95 if v.get("label") == "normal" else 0.50,
                    "trend": "stable",
                    "ttm_days": None,
                })
                sensor_health.append({
                    "station_id": sid,
                    "variable": var,
                    "score": h_var.get("score"),
                    "trend": h_var.get("trend"),
                    "ttm_days": h_var.get("ttm_days"),
                })
        return sensor_health

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket):
        await websocket.accept()
        state.active_websockets.append(websocket)
        try:
            while True:
                # Keep socket alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in state.active_websockets:
                state.active_websockets.remove(websocket)

    @app.post("/inject-fault")
    async def inject_fault(request: Request):
        payload = await request.json()
        preset = payload.get("preset")

        if preset == "55C":
            sid = payload.get("station_id", "INI0001")
            inj = {
                "station_id": sid,
                "variable": "T",
                "root_cause": "spike",
                "magnitude": 55.0,
                "count": 1,
            }
        else:
            sid = payload.get("station_id", "INI0001")
            var = payload.get("variable", "T")
            rc = payload.get("root_cause", "spike")
            mag = float(payload.get("magnitude", 55.0))
            dur_h = float(payload.get("duration_hours", 1.0))
            count = max(1, int(dur_h * 4))
            inj = {
                "station_id": sid,
                "variable": var,
                "root_cause": rc,
                "magnitude": mag,
                "count": count,
            }

        state.active_injections.append(inj)
        return {"status": "ok", "message": f"Fault injected for station {sid}", "injection": inj}

    @app.post("/replay/speed")
    async def set_replay_speed(request: Request):
        payload = await request.json()
        sf = float(payload.get("speed_factor", 0.0))
        state.speed_factor = sf
        return {"status": "ok", "speed_factor": sf}

    @app.get("/benchmark")
    def get_benchmark():
        reports = []
        if REPORTS_DIR.exists():
            for p in REPORTS_DIR.glob("**/*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    reports.append({"file": str(p.relative_to(REPORTS_DIR)), "data": data})
                except Exception:
                    pass

        if not reports:
            return {"status": "empty", "message": "no results yet", "reports": []}
        return {"status": "ok", "reports": reports}

    return app
