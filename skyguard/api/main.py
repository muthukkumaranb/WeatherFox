"""FastAPI + WebSocket + /inject-fault + /inject-event endpoint.  Owner: Person B.

Serves verdicts in real-time, manages background replay, fault injection,
genuine storm injection, sensor health board, and exposes dashboard APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..contract import check_window, ingest_row, validate_verdict
from ..eval.feedback import record_feedback
from ..ingest.buffers import BufferPool
from ..ingest.replay import (
    build_synthetic_registry, generate_synthetic_stream, load_replay_stream,
)
from ..ingest.rules import build_duplicate_verdict, detect_duplicate
from ..scorer import score

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
SAMPLE_STREAM_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "stream" / "sample_1day.jsonl"
DASHBOARD_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard"

# ---------------------------------------------------------------------------
# Genuine storm event profiles — physically consistent changes
# ---------------------------------------------------------------------------
EVENT_PROFILES: dict[str, dict] = {
    "heat_wave": {
        "T_delta": 6.0,    # +6 °C
        "RH_delta": -15.0,  # -15 %
        "P_delta": 0.0,
        "ramp_hours": 0,    # instant (sustained)
    },
    "squall": {
        "T_delta": -8.0,    # -8 °C
        "RH_delta": 30.0,   # +30 %
        "P_delta": 3.0,     # +3 hPa over 1 h then recovering
        "ramp_hours": 1,
    },
    "cyclone": {
        "T_delta": 0.0,
        "RH_delta": 20.0,   # +20 %
        "P_delta": -12.0,   # -12 hPa over 6 h
        "ramp_hours": 6,
    },
}


def get_default_speed_factor() -> float:
    """Load default speed_factor from config/skyguard.toml [replay]."""
    if CONFIG_PATH.exists() and tomllib is not None:
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
                return float(data.get("replay", {}).get("speed_factor", 1800.0))
        except Exception:
            pass
    return 1800.0


class StateManager:
    """In-memory state manager for live replay, websockets, and APIs."""

    def __init__(self) -> None:
        self.registry: dict[str, dict] = build_synthetic_registry()
        self.verdicts: deque[dict] = deque(maxlen=2000)
        self.raw_rows: dict[str, deque[dict]] = {}
        self.buffers: BufferPool = BufferPool(max_rows_per_station=200)
        self.seen_rows_by_station: dict[str, deque[dict]] = {}
        self.active_websockets: list[WebSocket] = []
        self.speed_factor: float = get_default_speed_factor()
        self.active_injections: list[dict] = []
        self.active_events: list[dict] = []  # genuine storm event injections
        self.alerts_feedback: dict[str, dict] = {}
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

    def get_neighbours(self, station_id: str) -> list[str]:
        """Return neighbour station IDs based on cluster membership."""
        target_info = self.registry.get(station_id, {})
        target_cluster = target_info.get("cluster")
        nbs = []
        for sid, info in self.registry.items():
            if sid != station_id:
                if target_cluster is not None and info.get("cluster") == target_cluster:
                    nbs.append(sid)
        return nbs

    def reset(self) -> None:
        self.verdicts.clear()
        self.raw_rows.clear()
        self.buffers = BufferPool(max_rows_per_station=200)
        self.seen_rows_by_station.clear()
        self.active_injections.clear()
        self.active_events.clear()
        self.alerts_feedback.clear()


state = StateManager()


def apply_injections(row: dict) -> dict:
    """Apply active fault injections to an incoming input row.

    Fault types match their names:
    - spike: value + magnitude ONCE (single reading)
    - frozen: repeat last real value for duration
    - offset: + magnitude for duration
    - drift: + rate × hours elapsed
    - out_of_range: fixed value (magnitude) for duration
    """
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
            dur_h = inj.get("duration_hours", 1.0)
            hours_done = inj.get("hours_done", 0.0)

            if inj["last_real_value"] is None and row_copy.get(var) is not None:
                inj["last_real_value"] = row_copy.get(var)

            step_h = 1.0  # 1 hour per round of simulation

            if cause == "spike":
                # Spike = value + magnitude ONCE
                curr = row_copy.get(var, 30.0) or 30.0
                row_copy[var] = round(curr + mag, 2)
                # Spike fires once then is done
                inj["hours_done"] = dur_h  # expire immediately
            elif cause == "frozen":
                # Frozen = repeat last real value for duration
                if inj["last_real_value"] is not None:
                    row_copy[var] = inj["last_real_value"]
                inj["hours_done"] = hours_done + step_h
            elif cause == "offset":
                # Offset = + magnitude for duration
                curr = row_copy.get(var)
                if curr is not None:
                    row_copy[var] = round(curr + mag, 2)
                inj["hours_done"] = hours_done + step_h
            elif cause == "drift":
                # Drift = + rate × hours elapsed
                curr = row_copy.get(var)
                if curr is not None:
                    inj["hours_done"] = hours_done + step_h
                    rate = mag
                    row_copy[var] = round(curr + rate * inj["hours_done"], 2)
            elif cause == "out_of_range":
                # Out of range = fixed value (magnitude)
                row_copy[var] = mag
                inj["hours_done"] = hours_done + step_h

            if inj["hours_done"] < dur_h:
                remaining.append(inj)
        else:
            remaining.append(inj)

    state.active_injections = remaining
    return row_copy


def apply_event_injections(row: dict) -> dict:
    """Apply active genuine event injections to an incoming input row.

    Unlike fault injections, event injections apply physically consistent
    changes to ALL affected stations (target + neighbours).
    """
    if not state.active_events:
        return row

    row_copy = dict(row)
    sid = row_copy.get("station_id")
    if not sid:
        return row_copy

    remaining: list[dict] = []
    for evt in state.active_events:
        affected_stations = evt.get("affected_stations", [])
        if sid in affected_stations:
            profile = EVENT_PROFILES.get(evt["kind"], {})
            hours_done = evt.get("hours_done", 0.0)
            dur_h = evt.get("duration_hours", 1.0)
            ramp_hours = profile.get("ramp_hours", 0)

            # Calculate ramp factor (0→1 over ramp_hours, then sustained)
            if ramp_hours > 0 and hours_done < ramp_hours:
                ramp_factor = min(1.0, hours_done / ramp_hours)
            else:
                ramp_factor = 1.0

            # For squall: P recovers after ramp, T and RH are sustained
            if evt["kind"] == "squall":
                # P ramps up over 1 h then recovers
                if hours_done <= ramp_hours:
                    p_factor = ramp_factor
                else:
                    # Recovery: linearly return to 0 over the same ramp time
                    recovery_elapsed = hours_done - ramp_hours
                    p_factor = max(0.0, 1.0 - recovery_elapsed / max(1.0, ramp_hours))
                if row_copy.get("P") is not None:
                    row_copy["P"] = round(row_copy["P"] + profile["P_delta"] * p_factor, 2)
            else:
                if row_copy.get("P") is not None and profile.get("P_delta"):
                    row_copy["P"] = round(row_copy["P"] + profile["P_delta"] * ramp_factor, 2)

            if row_copy.get("T") is not None and profile.get("T_delta"):
                row_copy["T"] = round(row_copy["T"] + profile["T_delta"] * ramp_factor, 2)
            if row_copy.get("RH") is not None and profile.get("RH_delta"):
                row_copy["RH"] = round(
                    max(0.0, min(100.0, row_copy["RH"] + profile["RH_delta"] * ramp_factor)), 2
                )

        # Only the originator increments hours_done; one per replay round
        if sid == evt.get("station_id"):
            evt["hours_done"] = evt.get("hours_done", 0.0) + 1.0

        if evt.get("hours_done", 0.0) < evt.get("duration_hours", 1.0):
            remaining.append(evt)
        else:
            # Keep expired events in remaining if not yet expired
            if sid != evt.get("station_id"):
                remaining.append(evt)

    state.active_events = remaining
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
    """Background task running continuous replay loop with simulated clock."""
    logger.info("Starting background replay loop...")
    state.running = True

    # Fixed 14-day window starting 2024-05-24T00:00:00Z (NW India Heatwave period)
    synthetic_window_start = datetime(2024, 5, 24, 0, 0, tzinfo=timezone.utc)
    total_window_hours = 14 * 24  # 336 hours

    sim_hour_offset = 0

    while state.running:
        if SAMPLE_STREAM_PATH.exists():
            raw_stream = list(load_replay_stream(SAMPLE_STREAM_PATH))
        else:
            raw_stream = generate_synthetic_stream(num_stations=12, rows_per_station=1)

        seen_in_round: set[str] = set()

        for raw_row in raw_stream:
            # Yield execution to event loop per row for high responsiveness
            await asyncio.sleep(0)

            if not state.running:
                break

            row = dict(raw_row)
            sid = row.get("station_id")

            # At the start of a new round of stations (new simulated hour):
            if sid in seen_in_round:
                sim_hour_offset = (sim_hour_offset + 1) % total_window_hours
                seen_in_round.clear()

                # Pace by simulated time: sleep (3600 / speed_factor) real seconds per simulated hour!
                sf = max(0.1, state.speed_factor)
                pacing_sleep = 3600.0 / sf
                await asyncio.sleep(pacing_sleep)

            if sid:
                seen_in_round.add(sid)

            sim_time = synthetic_window_start + timedelta(hours=sim_hour_offset)
            ts_iso = sim_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            ingest_ts_iso = (sim_time + timedelta(seconds=random.randint(1, 5))).strftime("%Y-%m-%dT%H:%M:%SZ")
            row["ts_utc"] = ts_iso
            row["ingest_ts_utc"] = ingest_ts_iso

            # 1. Apply fault injections
            injected_row = apply_injections(row)
            # 1b. Apply genuine event injections
            injected_row = apply_event_injections(injected_row)

            # 2. Add raw row to history
            state.add_raw_row(injected_row)

            # 3. Ingest validation
            valid_row = ingest_row(injected_row)
            if valid_row is None:
                continue

            target_id = valid_row["station_id"]

            # 4. Duplicate check using bounded deque
            if target_id not in state.seen_rows_by_station:
                state.seen_rows_by_station[target_id] = deque(maxlen=200)
            st_history = state.seen_rows_by_station[target_id]
            st_history.append(valid_row)

            dup_indices = detect_duplicate(list(st_history))
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
            for nb_sid, info in state.registry.items():
                if nb_sid != target_id:
                    if target_cluster is not None and info.get("cluster") == target_cluster:
                        nb_w = state.buffers.window(nb_sid)
                        if nb_w:
                            station_window[nb_sid] = nb_w

            # 7. Call scorer off the event loop thread
            try:
                verdict = await asyncio.to_thread(score, station_window, target_id)
                state.add_verdict(verdict)
                await broadcast_verdict(verdict)
            except Exception as exc:
                logger.error("Scorer error for station %s: %s", target_id, exc)

        # After finishing stream pass, advance 1 hour and sleep for pacing
        sim_hour_offset = (sim_hour_offset + 1) % total_window_hours
        sf = max(0.1, state.speed_factor)
        pacing_sleep = 3600.0 / sf
        await asyncio.sleep(pacing_sleep)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager starting background replay."""
    state.reset()
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


def get_scorer_info() -> dict[str, Any]:
    """Return information about the active scorer backend and model version."""
    backend = os.environ.get("SKYGUARD_SCORER", "fake")
    if backend == "fake":
        from ..fake_score import MODEL_VERSION
        return {
            "backend": "fake",
            "model_version": MODEL_VERSION,
            "banner_text": "DEMO MODE: fake scorer",
            "banner_level": "warning",
        }
    elif backend == "real":
        try:
            from ..verdict.api import score as _score  # noqa: F401
            # If we got here the real backend is importable
            model_v = "untrained"
            models_dir = Path(__file__).resolve().parent.parent.parent / "models"
            if models_dir.exists() and any(models_dir.iterdir()):
                # Attempt to read version from a marker file
                ver_file = models_dir / "version.txt"
                if ver_file.exists():
                    model_v = ver_file.read_text().strip()
                else:
                    model_v = "untrained"
            banner_level = "danger" if model_v == "untrained" else "info"
            banner_text = f"model {model_v}" + (" (untrained)" if model_v == "untrained" else "")
            return {
                "backend": "real",
                "model_version": model_v,
                "banner_text": banner_text,
                "banner_level": banner_level,
            }
        except (ImportError, NotImplementedError):
            return {
                "backend": "real",
                "model_version": "unavailable",
                "banner_text": "REAL SCORER: import failed",
                "banner_level": "danger",
            }
    return {
        "backend": backend,
        "model_version": "unknown",
        "banner_text": f"Unknown scorer: {backend}",
        "banner_level": "danger",
    }


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

    @app.get("/scorer-info")
    def scorer_info():
        return get_scorer_info()

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
                "genuine_event": lv.get("genuine_event", False),
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
                "genuine_event": v.get("genuine_event", False),
                "corrected_T": vars_v.get("T", {}).get("corrected", {}).get("value"),
                "corrected_RH": vars_v.get("RH", {}).get("corrected", {}).get("value"),
                "corrected_P": vars_v.get("P", {}).get("corrected", {}).get("value"),
            }
            series.append(item)
        return {"station_id": station_id, "hours": hours, "series": series}

    @app.post("/alerts/{alert_id}/ack")
    async def ack_alert(alert_id: str, request: Request):
        payload = await request.json()
        new_state = payload.get("state", "acknowledged")
        reason = payload.get("reason", None)
        note = payload.get("note", "")
        by = payload.get("by", "operator")

        fb_entry = {
            "alert_id": alert_id,
            "state": new_state,
            "reason": reason,
            "note": note,
            "by": by,
            "timestamp_recorded": datetime.now(timezone.utc).isoformat(),
        }

        matching_v = None
        for v in state.verdicts:
            v_id = f"{v.get('station_id')}_{v.get('ts_utc')}"
            if v_id == alert_id or alert_id == v.get("station_id") or alert_id.startswith(v.get("station_id", "")):
                matching_v = v
                break

        if matching_v:
            fb_entry["station_id"] = matching_v.get("station_id")
            fb_entry["ts_utc"] = matching_v.get("ts_utc")

        state.alerts_feedback[alert_id] = fb_entry
        record_feedback(fb_entry)
        return {"status": "ok", "alert_id": alert_id, "state": new_state, "feedback": fb_entry}

    @app.get("/alerts")
    def get_alerts(request: Request, since: str | None = None):
        target_state = request.query_params.get("state")
        alerts = []
        for v in reversed(state.verdicts):
            if v.get("label") in ("anomaly", "uncertain"):
                if since and v.get("ts_utc", "") < since:
                    continue
                v_id = f"{v.get('station_id')}_{v.get('ts_utc')}"
                fb = state.alerts_feedback.get(v_id) or state.alerts_feedback.get(v.get("station_id"))
                st_val = fb.get("state") if fb else "open"

                if target_state and st_val != target_state:
                    continue

                v_copy = dict(v)
                v_copy["alert_id"] = v_id
                v_copy["state"] = st_val
                if fb:
                    v_copy["reason"] = fb.get("reason")
                    v_copy["note"] = fb.get("note")
                    v_copy["by"] = fb.get("by")
                alerts.append(v_copy)
        return alerts

    @app.get("/export")
    def export_csv(station_id: str | None = None, from_ts: str | None = None, to_ts: str | None = None):
        lines = ["ts_utc,station_id,T,RH,P,T_flag,RH_flag,P_flag,T_corrected,T_sigma,RH_corrected,RH_sigma,P_corrected,P_sigma"]

        for v in state.verdicts:
            st = v.get("station_id")
            ts = v.get("ts_utc")
            if station_id and st != station_id:
                continue
            if from_ts and ts < from_ts:
                continue
            if to_ts and ts > to_ts:
                continue

            raw_list = state.raw_rows.get(st, [])
            raw_row = next((r for r in raw_list if r.get("ts_utc") == ts), {})

            t_val = raw_row.get("T", "")
            rh_val = raw_row.get("RH", "")
            p_val = raw_row.get("P", "")

            vars_v = v.get("vars", {})

            def get_flag_and_corrected(var_name: str, raw_v: Any):
                if raw_v is None or raw_v == "":
                    return 9, "", ""
                info = vars_v.get(var_name, {})
                lbl = info.get("label", "normal")
                if lbl == "normal":
                    flag = 0
                elif lbl == "uncertain":
                    flag = 2
                elif lbl == "anomaly":
                    flag = 3
                else:
                    flag = 1

                if flag in (2, 3):
                    corr = info.get("corrected", {})
                    corr_v = corr.get("value", raw_v) if isinstance(corr, dict) else raw_v
                    sigma_v = corr.get("sigma", 0.5) if isinstance(corr, dict) else 0.5
                    return flag, corr_v, sigma_v
                else:
                    return flag, "", ""

            t_flag, t_corr, t_sig = get_flag_and_corrected("T", t_val)
            rh_flag, rh_corr, rh_sig = get_flag_and_corrected("RH", rh_val)
            p_flag, p_corr, p_sig = get_flag_and_corrected("P", p_val)

            lines.append(f"{ts},{st},{t_val},{rh_val},{p_val},{t_flag},{rh_flag},{p_flag},{t_corr},{t_sig},{rh_corr},{rh_sig},{p_corr},{p_sig}")

        csv_body = "\n".join(lines)
        fn = f"skyguard_export_{station_id or 'all'}.csv"
        return Response(
            content=csv_body,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={fn}"},
        )

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
            # 55 °C is an out_of_range fault (fixed value), NOT a spike
            sid = payload.get("station_id", "INI0001")
            inj = {
                "station_id": sid,
                "variable": "T",
                "root_cause": "out_of_range",
                "magnitude": 55.0,
                "duration_hours": 6.0,
                "hours_done": 0.0,
                "last_real_value": None,
            }
        else:
            sid = payload.get("station_id", "INI0001")
            var = payload.get("variable", "T")
            rc = payload.get("root_cause", "spike")
            mag = float(payload.get("magnitude", 55.0))
            dur_h = float(payload.get("duration_hours", 6.0))
            inj = {
                "station_id": sid,
                "variable": var,
                "root_cause": rc,
                "magnitude": mag,
                "duration_hours": dur_h,
                "hours_done": 0.0,
                "last_real_value": None,
            }

        state.active_injections.append(inj)
        return {"status": "ok", "message": f"Fault injected for station {sid}", "injection": inj}

    @app.post("/inject-event")
    async def inject_event(request: Request):
        """Inject a genuine weather event (heat_wave, squall, cyclone).

        Applies physically consistent changes to the target station AND all
        its neighbours.  The fake scorer will recognise the coherent neighbour
        deviation and label them as genuine_event (not anomaly).
        """
        payload = await request.json()
        sid = payload.get("station_id", "INI0001")
        kind = payload.get("kind", "heat_wave")
        dur_h = float(payload.get("duration_hours", 6.0))

        if kind not in EVENT_PROFILES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown event kind '{kind}'. Must be one of: {list(EVENT_PROFILES.keys())}",
            )

        # Get affected stations: target + all neighbours
        affected = [sid] + state.get_neighbours(sid)

        evt = {
            "station_id": sid,
            "kind": kind,
            "duration_hours": dur_h,
            "hours_done": 0.0,
            "affected_stations": affected,
        }
        state.active_events.append(evt)

        return {
            "status": "ok",
            "message": f"Genuine {kind} event injected for {sid} + {len(affected) - 1} neighbours",
            "event": evt,
        }

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
