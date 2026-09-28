"""FastAPI + WebSocket + /inject-fault endpoint.  Owner: Person B.

Serves verdicts in real-time, manages background replay, fault injection,
sensor health board, and exposes dashboard APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..contract import check_window, ingest_row, validate_verdict
from ..ingest.buffers import BufferPool
from ..ingest.replay import (
    build_synthetic_registry, generate_synthetic_stream, load_replay_stream,
)
from ..ingest.rules import build_duplicate_verdict, detect_duplicate
from ..scorer import score

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
SAMPLE_STREAM_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "stream" / "sample_1day.jsonl"
DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard"


def get_default_speed_factor() -> float:
    """Load default speed_factor from config/skyguard.toml [replay]."""
    if CONFIG_PATH.exists() and tomllib is not None:
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                return float(data.get("replay", {}).get("speed_factor", 3600.0))
        except Exception:
            pass
    return 3600.0


class StateManager:
    """In-memory state manager for live replay, websockets, and APIs."""

    def __init__(self) -> None:
        self.registry: dict[str, dict] = build_synthetic_registry()
        self.verdicts: deque[dict] = deque(maxlen=2000)
        self.raw_rows: dict[str, deque[dict]] = {}
        self.buffers: BufferPool = BufferPool(max_rows_per_station=200)
        self.seen_rows_by_station: dict[str, list[dict]] = {}
        self.active_websockets: list[WebSocket] = []
        self.speed_factor: float = get_default_speed_factor()
        self.active_injections: list[dict] = []
        self.running: bool = False
        self.replay_task: asyncio.Task | None = None
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
    if not sid:
        return row_copy

    remaining: list[dict] = []
    for inj in state.active_injections:
        if inj["station_id"] == sid:
            var = inj["variable"]
            cause = inj["root_cause"]
            mag = inj["magnitude"]

            if inj["last_real_value"] is None and row_copy.get(var) is not None:
                inj["last_real_value"] = row_copy.get(var)

            if cause == "spike":
                if inj.get("is_preset_55c"):
                    row_copy["T"] = 55.0
                else:
                    curr = row_copy.get(var, 30.0) or 30.0
                    row_copy[var] = round(curr + mag, 2)
                inj["readings_done"] += 1
            elif cause == "frozen":
                if inj["last_real_value"] is not None:
                    row_copy[var] = inj["last_real_value"]
                else:
                    row_copy[var] = mag
                inj["readings_done"] += 1
            elif cause == "offset":
                curr = row_copy.get(var)
                if curr is not None:
                    row_copy[var] = round(curr + mag, 2)
                inj["readings_done"] += 1
            elif cause == "drift":
                curr = row_copy.get(var)
                if curr is not None:
                    frac = min(1.0, inj["readings_done"] / max(1, inj["target_readings"]))
                    row_copy[var] = round(curr + (mag * frac), 2)
                inj["readings_done"] += 1
            elif cause == "out_of_range":
                row_copy[var] = mag
                inj["readings_done"] += 1

            if inj["readings_done"] < inj["target_readings"]:
                remaining.append(inj)
        else:
            remaining.append(inj)

    state.active_injections = remaining
    return row_copy


async def broadcast_verdict(verdict: dict) -> None:
    """Broadcast a verdict to all connected WebSocket clients."""
    if not state.active_websockets:
        return

    dead_sockets = []
    for ws in list(state.active_websockets):
        try:
            await ws.send_json(verdict)
        except Exception:
            dead_sockets.append(ws)

    for ws in dead_sockets:
        if ws in state.active_websockets:
            state.active_websockets.remove(ws)


async def run_background_replay() -> None:
    """Background task running continuous replay loop."""
    logger.info("Starting background replay loop...")
    state.running = True

    sim_step = 0
    while state.running:
        # Generate or load stream rows
        if SAMPLE_STREAM_PATH.exists():
            raw_stream = list(load_replay_stream(SAMPLE_STREAM_PATH))
        else:
            raw_stream = generate_synthetic_stream(num_stations=12, rows_per_station=10)

        # Update timestamps for continuous loop
        base_dt = datetime.now(timezone.utc)

        for i, raw_row in enumerate(raw_stream):
            if not state.running:
                break

            row = dict(raw_row)
            sim_step += 1
            # Stamp timestamps continuously
            ts_iso = base_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            row["ts_utc"] = ts_iso
            row["ingest_ts_utc"] = ts_iso

            # 1. Apply fault injections
            injected_row = apply_injections(row)

            # 2. Add raw row to history
            state.add_raw_row(injected_row)

            # 3. Ingest validation
            valid_row = ingest_row(injected_row)
            if valid_row is None:
                continue

            target_id = valid_row["station_id"]

            # 4. Duplicate check
            st_history = state.seen_rows_by_station.setdefault(target_id, [])
            st_history.append(valid_row)
            dup_indices = detect_duplicate(st_history)

            if len(st_history) - 1 in dup_indices:
                dup_verdict = build_duplicate_verdict(valid_row)
                state.add_verdict(dup_verdict)
                await broadcast_verdict(dup_verdict)
                st_history.pop()
                continue

            # 5. Push to buffer
            state.buffers.push(valid_row)

            # 6. Build station_window for target
            target_window = state.buffers.window(target_id)
            station_window: dict[str, list[dict]] = {target_id: target_window}

            # Find neighbours
            target_info = state.registry.get(target_id, {})
            target_cluster = target_info.get("cluster")
            for sid, info in state.registry.items():
                if sid != target_id:
                    if target_cluster is not None and info.get("cluster") == target_cluster:
                        nb_w = state.buffers.window(sid)
                        if nb_w:
                            station_window[sid] = nb_w

            # 7. Call scorer
            try:
                verdict = score(station_window, target=target_id)
                state.add_verdict(verdict)
                await broadcast_verdict(verdict)
            except Exception as exc:
                logger.error("Scorer error for station %s: %s", target_id, exc)

            # Delay according to speed_factor
            sf = max(0.1, state.speed_factor)
            # 15 min cadence (900 s) divided by speed_factor
            delay = min(0.5, max(0.001, 900.0 / sf))
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager starting background replay."""
    state.running = True
    state.replay_task = asyncio.create_task(run_background_replay())
    try:
        yield
    finally:
        state.running = False
        if state.replay_task:
            state.replay_task.cancel()
            try:
                await state.replay_task
            except asyncio.CancelledError:
                pass


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
    app = FastAPI(title="SkyGuard AI API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if (DASHBOARD_DIR / "vendor").exists():
        app.mount("/vendor", StaticFiles(directory=str(DASHBOARD_DIR / "vendor")), name="vendor")

    @app.get("/")
    def read_root():
        index_file = DASHBOARD_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "SkyGuard AI API is running."}

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
                "duration_hours": 0.25,
                "target_readings": 1,
                "readings_done": 0,
                "is_preset_55c": True,
                "last_real_value": None,
            }
        else:
            sid = payload.get("station_id", "INI0001")
            var = payload.get("variable", "T")
            rc = payload.get("root_cause", "spike")
            mag = float(payload.get("magnitude", 55.0))
            dur_h = float(payload.get("duration_hours", 1.0))
            # Convert duration_hours to target_readings (15 min cadence -> 4 readings per hour)
            target_readings = max(1, int(dur_h * 4))
            inj = {
                "station_id": sid,
                "variable": var,
                "root_cause": rc,
                "magnitude": mag,
                "duration_hours": dur_h,
                "target_readings": target_readings,
                "readings_done": 0,
                "is_preset_55c": False,
                "last_real_value": None,
            }

        state.active_injections.append(inj)
        return {"status": "ok", "message": f"Fault injected for station {sid}", "injection": inj}

    @app.post("/replay/speed")
    async def set_replay_speed(request: Request):
        payload = await request.json()
        sf = float(payload.get("speed_factor", 3600.0))
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
