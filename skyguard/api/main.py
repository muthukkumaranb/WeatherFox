"""FastAPI + WebSocket + /inject-fault + /inject-event endpoint.  Owner: Person B.

Serves verdicts in real-time, manages background replay, fault injection,
genuine storm injection, sensor health board, and exposes dashboard APIs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
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
from ..ingest.replay import (
    BufferPool,
    build_synthetic_registry,
    compute_neighbours_for_station,
    generate_synthetic_stream,
    load_replay_stream,
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
    "storm": {
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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def get_neighbours_by_distance(station_id: str, registry: dict[str, dict], max_km: float = 200.0) -> list[str]:
    return compute_neighbours_for_station(station_id, registry)


def load_wis2_registry(csv_path: Path | str = "data/wis2/stations.csv") -> dict[str, dict]:
    path = Path(csv_path)
    reg: dict[str, dict] = {}
    if not path.exists():
        return reg
    import csv
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("station_id") or row.get("id")
            if sid:
                elev = 0.0
                for k in ("elev_m", "elevation", "elev"):
                    if k in row and row[k] != "":
                        try:
                            elev = float(row[k])
                            break
                        except ValueError:
                            pass
                reg[sid] = {
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "elevation": elev,
                }
    return reg


class StateManager:
    """In-memory state manager for live replay, websockets, and APIs."""

    def __init__(self) -> None:
        self.replay_mode: str = os.environ.get("SKYGUARD_REPLAY_MODE", "synthetic")
        self.live_ingest_time: str | None = None
        self._registry: dict[str, dict] = build_synthetic_registry()
        self._neighbour_cache: dict[str, list[str]] = {}
        self._neighbour_cache_reg_id: int | None = None
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
        self.duplicates_dropped: int = 0
        self.last_ts_by_station: dict[str, str] = {}
        self.seen_station_ts: set[tuple[str, str]] = set()

    @property
    def registry(self) -> dict[str, dict]:
        return self._registry

    @registry.setter
    def registry(self, val: dict[str, dict]) -> None:
        self._registry = val
        self.recompute_neighbour_cache()

    def recompute_neighbour_cache(self) -> None:
        self._neighbour_cache = {
            sid: compute_neighbours_for_station(sid, self._registry)
            for sid in self._registry
        }
        self._neighbour_cache_reg_id = id(self._registry)

    def get_neighbours(self, station_id: str) -> list[str]:
        if (
            not hasattr(self, "_neighbour_cache")
            or self._neighbour_cache_reg_id != id(self._registry)
        ):
            self.recompute_neighbour_cache()
        return self._neighbour_cache.get(station_id, [])

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

    def reset(self) -> None:
        self.verdicts.clear()
        self.raw_rows.clear()
        self.buffers = BufferPool(max_rows_per_station=200)
        self.seen_rows_by_station.clear()
        self.active_injections.clear()
        self.active_events.clear()
        self.alerts_feedback.clear()
        self.duplicates_dropped = 0
        self.last_ts_by_station.clear()
        self.seen_station_ts.clear()
        if self.replay_mode == "live":
            wis2_reg = Path(__file__).resolve().parent.parent.parent / "data" / "wis2" / "stations.csv"
            if wis2_reg.exists():
                self.registry = load_wis2_registry(wis2_reg)
        else:
            self.registry = build_synthetic_registry()



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
            row_copy["injected"] = True
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
            elif cause == "radiation":
                # Radiation shield heating: daytime warm bias (+3 to +6 °C scaled by sun elevation)
                curr = row_copy.get(var, 30.0) or 30.0
                ts_str = row_copy.get("ts_utc")
                utc_hour = 12.0
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        utc_hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
                    except Exception:
                        pass
                lon = state.registry.get(sid, {}).get("lon", 77.2) if hasattr(state, "registry") else 77.2
                solar_hour = (utc_hour + lon / 15.0) % 24.0
                if 6.0 <= solar_hour <= 18.0:
                    sun_factor = max(0.0, math.sin(math.pi * (solar_hour - 6.0) / 12.0))
                else:
                    sun_factor = 0.0
                row_copy[var] = round(curr + mag * sun_factor, 2)
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
            # Tag row as genuine event
            row_copy["genuine_event"] = True
            row_copy["is_genuine_event"] = True

            profile = EVENT_PROFILES.get(evt["kind"], {})
            hours_done = evt.get("hours_done", 0.0)
            dur_h = evt.get("duration_hours", 1.0)
            ramp_hours = profile.get("ramp_hours", 0)

            # Calculate ramp factor (0→1 over ramp_hours at start, 1→0 over final 1h at end)
            if ramp_hours > 0 and hours_done < ramp_hours:
                ramp_factor = min(1.0, hours_done / ramp_hours)
            elif dur_h > 1.0 and hours_done >= dur_h - 1.0:
                ramp_factor = max(0.0, (dur_h - hours_done) / 1.0)
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
                if row_copy.get("Td") is not None and row_copy["Td"] > row_copy["T"] - 1.0:
                    row_copy["Td"] = round(row_copy["T"] - 1.0, 2)
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
    loop_count = 0

    wis2_stream = Path(__file__).resolve().parent.parent.parent / "data" / "stream" / "wis2_latest.jsonl"
    wis2_reg = Path(__file__).resolve().parent.parent.parent / "data" / "wis2" / "stations.csv"

    is_live = (state.replay_mode == "live") and wis2_stream.exists() and wis2_reg.exists()
    if is_live:
        state.registry = load_wis2_registry(wis2_reg)
    else:
        state.registry = build_synthetic_registry()

    while state.running:
        if is_live:
            if wis2_stream.exists():
                raw_stream = list(load_replay_stream(wis2_stream))
                raw_stream.sort(key=lambda r: r.get("ts_utc") or r.get("ingest_ts_utc") or "")
            else:
                raw_stream = []
        elif SAMPLE_STREAM_PATH.exists():
            try:
                SAMPLE_STREAM_PATH.unlink()
            except Exception:
                pass
            raw_stream = generate_synthetic_stream(num_stations=12, rows_per_station=14 * 24, start_ts="2024-05-24T00:00:00Z")
        else:
            raw_stream = generate_synthetic_stream(num_stations=12, rows_per_station=14 * 24, start_ts="2024-05-24T00:00:00Z")

        for r in raw_stream:
            sid = r.get("station_id")
            if sid and sid not in state.registry:
                st_name = r.get("name") or (state.registry.get(sid, {}).get("name") if hasattr(state, "registry") else None) or f"AWS {sid}"
                state.registry[sid] = {
                    "station_id": sid,
                    "name": st_name,
                    "lat": r.get("lat", 20.0),
                    "lon": r.get("lon", 78.0),
                    "elevation": r.get("elevation", r.get("elev_m", 0.0)),
                }

        seen_in_round: set[str] = set()



        for raw_row in raw_stream:
            # Yield execution to event loop per row for high responsiveness
            await asyncio.sleep(0)

            if not state.running:
                break

            row = dict(raw_row)
            sid = row.get("station_id")

            if is_live:
                ts = row.get("ts_utc") or row.get("ingest_ts_utc")
                if not sid or not ts:
                    continue

                last_ts = state.last_ts_by_station.get(sid)
                if last_ts and ts <= last_ts:
                    if sid in state.seen_rows_by_station:
                        st_history = state.seen_rows_by_station[sid]
                        prev_match = next((pr for pr in reversed(st_history) if pr.get("ts_utc") == ts), None)
                        if prev_match and all(prev_match.get(k) == row.get(k) for k in ("T", "Td", "RH", "P", "P_type")):
                            state.duplicates_dropped += 1
                    continue

                state.last_ts_by_station[sid] = ts
                state.live_ingest_time = ts
            else:
                # At the start of a new round of stations (new simulated hour):
                if sid in seen_in_round:
                    prev_offset = sim_hour_offset
                    sim_hour_offset = (sim_hour_offset + 1) % total_window_hours
                    if sim_hour_offset == 0 and prev_offset > 0:
                        loop_count += 1
                    seen_in_round.clear()

                    sf = max(0.1, state.speed_factor)
                    pacing_sleep = 3600.0 / sf
                    await asyncio.sleep(pacing_sleep)


                if sid:
                    seen_in_round.add(sid)

                # Shift timestamps forward on loop restart to guarantee strictly increasing ts
                sim_time = synthetic_window_start + timedelta(hours=sim_hour_offset + loop_count * total_window_hours)
                ts_iso = sim_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                ingest_ts_iso = (sim_time + timedelta(seconds=random.randint(1, 5))).strftime("%Y-%m-%dT%H:%M:%SZ")
                row["ts_utc"] = ts_iso
                row["ingest_ts_utc"] = ingest_ts_iso

                ts_key = (sid, ts_iso)
                if ts_key in state.seen_station_ts:
                    continue
                state.seen_station_ts.add(ts_key)

            # 1. Apply genuine event injections first (atmosphere)
            injected_row = apply_event_injections(row)
            # 2. Apply fault injections on top (sensor)
            injected_row = apply_injections(injected_row)

            # 2. Add raw row to history
            state.add_raw_row(injected_row)

            # 3. Ingest validation
            valid_row = ingest_row(injected_row)
            if valid_row is None:
                continue

            target_id = valid_row["station_id"]
            ts_utc = valid_row["ts_utc"]

            # 4. Duplicate check using bounded deque
            if target_id not in state.seen_rows_by_station:
                state.seen_rows_by_station[target_id] = deque(maxlen=200)
            st_history = state.seen_rows_by_station[target_id]

            prev_match = None
            for prev_r in reversed(st_history):
                if prev_r.get("ts_utc") == ts_utc:
                    prev_match = prev_r
                    break
                try:
                    dt1 = datetime.fromisoformat(prev_r["ts_utc"].replace("Z", "+00:00"))
                    dt2 = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
                    if abs((dt2 - dt1).total_seconds()) <= 180:
                        prev_match = prev_r
                        break
                except Exception:
                    pass

            if prev_match is not None:
                is_exact = all(
                    prev_match.get(k) == valid_row.get(k)
                    for k in ("T", "Td", "RH", "P", "P_type")
                )
                if is_exact:
                    state.duplicates_dropped += 1
                    continue
                else:
                    n_nbs = len(state.get_neighbours(target_id))
                    support = "neighbours_normal" if n_nbs > 0 else "no_neighbours"
                    dup_verdict = build_duplicate_verdict(valid_row, n_neighbours=n_nbs, spatial_support=support)
                    state.add_verdict(dup_verdict)
                    await broadcast_verdict(dup_verdict)
                    continue

            st_history.append(valid_row)

            # 5. Push to buffer
            state.buffers.push(valid_row)

            # 6. Build station_window for target
            target_window = state.buffers.window(target_id)
            station_window: dict[str, list[dict]] = {target_id: target_window}

            # Find neighbours
            for nb_sid in state.get_neighbours(target_id):
                nb_w = state.buffers.window(nb_sid)
                if nb_w:
                    station_window[nb_sid] = nb_w

            # 7. Call scorer off the event loop thread
            try:
                verdict = await asyncio.to_thread(score, station_window, target_id, registry=state.registry)
                state.add_verdict(verdict)
                await broadcast_verdict(verdict)
            except Exception as exc:
                logger.error("Scorer error for station %s: %s", target_id, exc)

        if is_live:
            # Idle for 5 minutes (300 sec) before re-checking live file for new reports
            for _ in range(300):
                if not state.running:
                    break
                await asyncio.sleep(1.0)
        else:
            # After finishing stream pass, advance 1 hour and sleep for pacing
            prev_offset = sim_hour_offset
            sim_hour_offset = (sim_hour_offset + 1) % total_window_hours
            if sim_hour_offset == 0 and prev_offset > 0:
                loop_count += 1
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


def health_check() -> dict[str, Any]:
    """GET /health endpoint handler."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "duplicates_dropped": getattr(state, "duplicates_dropped", 0),
    }


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
    replay_m = getattr(state, "replay_mode", os.environ.get("SKYGUARD_REPLAY_MODE", "synthetic"))

    wis2_stream = Path(__file__).resolve().parent.parent.parent / "data" / "stream" / "wis2_latest.jsonl"
    wis2_reg = Path(__file__).resolve().parent.parent.parent / "data" / "wis2" / "stations.csv"

    if replay_m == "live":
        ingest_time = getattr(state, "live_ingest_time", None)
        if not ingest_time and wis2_stream.exists():
            try:
                first_row = next(load_replay_stream(wis2_stream))
                ingest_time = first_row.get("ingest_ts_utc") or first_row.get("ts_utc")
            except Exception:
                pass
        ingest_str = ingest_time or "latest"
        return {
            "backend": backend,
            "model_version": "live",
            "banner_text": f"LIVE: IMD WIS2 (fetched {ingest_str}) — Up to date — waiting for next IMD report",
            "banner_level": "info",
        }


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




def build_benchmark_report(reports_dir: Path | str | None = None) -> dict[str, Any]:
    """Build structured benchmark response from reports directory.

    Sections:
    - detection: from reports/final/metrics.json
    - genuine_events: per event window from reports/final/metrics.json
    - drift: days-to-detect vs drift rate bins from reports/final/metrics.json
    - hadisd: agreement with HadISD flags, Indian stations from reports/hadisd/*.json
    - scale: 100 / 1,000 / 10,000 stations results from reports/scale/results.json
    - edge: reports/edge/edge.json + energy.json (labelled "host-measured estimate" / "estimated")
    """
    if reports_dir is None:
        reports_dir = REPORTS_DIR
    else:
        reports_dir = Path(reports_dir)

    def _load_json(p: Path) -> dict | None:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    # 1. Detection — ONLY reports/final/metrics.json (never reports/e2e_*)
    final_metrics_file = reports_dir / "final" / "metrics.json"
    metrics_data = _load_json(final_metrics_file)

    if metrics_data is not None:
        if "arms" in metrics_data and isinstance(metrics_data["arms"], dict):
            raw_arms = metrics_data["arms"]
            normalized_arms = {}
            for arm_k, arm_v in raw_arms.items():
                if isinstance(arm_v, dict):
                    av = dict(arm_v)
                    summary = av.get("summary", av)
                    if "f1" not in av and "f1" in summary:
                        av["f1"] = summary["f1"]
                    elif "f1" not in av and "f1_score" in summary:
                        av["f1"] = summary["f1_score"]
                    if "event_recall" not in av and "event_recall" in summary:
                        av["event_recall"] = summary["event_recall"]
                    if "precision" not in av and "precision" in summary:
                        av["precision"] = summary["precision"]
                    normalized_arms[arm_k] = av
                else:
                    normalized_arms[arm_k] = arm_v
            detection_section = {
                "status": "ok",
                "context": metrics_data.get("context", "context missing in reports/final/metrics.json"),
                "source_file": "reports/final/metrics.json",
                "arms": normalized_arms,
            }
        else:
            detection_section = {
                "status": "invalid_format",
                "context": metrics_data.get("context", "context missing in reports/final/metrics.json"),
                "source_file": "reports/final/metrics.json",
                "arms": None,
            }
    else:
        detection_section = {
            "status": "pending",
            "context": "context missing in reports/final/metrics.json",
            "source_file": "reports/final/metrics.json",
            "arms": None,
        }

    # 2. Genuine Events
    gen_data = None
    gen_context = "context missing in reports/final/metrics.json"
    if metrics_data is not None:
        gen_context = metrics_data.get("genuine_events_context", metrics_data.get("context", "context missing in reports/final/metrics.json"))
        if "genuine_events" in metrics_data or "genuine_events_table" in metrics_data:
            gen_data = metrics_data.get("genuine_events") or metrics_data.get("genuine_events_table")
        elif "arms" in metrics_data and isinstance(metrics_data["arms"], dict):
            extracted = {arm: arm_v.get("genuine_events") or arm_v.get("genuine_events_table") for arm, arm_v in metrics_data["arms"].items() if isinstance(arm_v, dict) and ("genuine_events" in arm_v or "genuine_events_table" in arm_v)}
            if extracted:
                gen_data = extracted

    if gen_data is not None:
        genuine_section = {
            "status": "ok",
            "context": gen_context,
            "source_file": "reports/final/metrics.json",
            "events": gen_data,
        }
    else:
        genuine_section = {
            "status": "pending",
            "context": "context missing in reports/final/metrics.json",
            "source_file": "reports/final/metrics.json",
            "events": None,
        }

    # 3. Drift
    drift_data = None
    drift_context = "context missing in reports/final/metrics.json"
    if metrics_data is not None:
        drift_context = metrics_data.get("drift_context", metrics_data.get("context", "context missing in reports/final/metrics.json"))
        if "drift" in metrics_data or "drift_table" in metrics_data:
            drift_data = metrics_data.get("drift") or metrics_data.get("drift_table")
        elif "arms" in metrics_data and isinstance(metrics_data["arms"], dict):
            extracted = {arm: arm_v.get("drift") or arm_v.get("drift_table") for arm, arm_v in metrics_data["arms"].items() if isinstance(arm_v, dict) and ("drift" in arm_v or "drift_table" in arm_v)}
            if extracted:
                drift_data = extracted

    if drift_data is not None:
        drift_section = {
            "status": "ok",
            "context": drift_context,
            "source_file": "reports/final/metrics.json",
            "bins": drift_data,
        }
    else:
        drift_section = {
            "status": "pending",
            "context": "context missing in reports/final/metrics.json",
            "source_file": "reports/final/metrics.json",
            "bins": None,
        }

    # 4. HadISD
    hadisd_dir = reports_dir / "hadisd"
    hadisd_files = list(hadisd_dir.glob("*.json")) if hadisd_dir.exists() else []
    if hadisd_files:
        hadisd_file = hadisd_files[0]
        hadisd_data = _load_json(hadisd_file)
        if hadisd_data is not None:
            hadisd_section = {
                "status": "ok",
                "context": hadisd_data.get("context", f"context missing in reports/hadisd/{hadisd_file.name}"),
                "source_file": f"reports/hadisd/{hadisd_file.name}",
                "results": hadisd_data,
            }
        else:
            hadisd_section = {
                "status": "pending",
                "context": f"context missing in reports/hadisd/{hadisd_file.name}",
                "source_file": f"reports/hadisd/{hadisd_file.name}",
                "results": None,
            }
    else:
        hadisd_section = {
            "status": "pending",
            "context": "context missing in reports/hadisd/*.json",
            "source_file": "reports/hadisd/*.json",
            "results": None,
        }

    # 5. Scale
    scale_file = reports_dir / "scale" / "results.json"
    scale_data = _load_json(scale_file)
    if scale_data is not None:
        scale_section = {
            "status": "ok",
            "context": scale_data.get("context", "context missing in reports/scale/results.json"),
            "source_file": "reports/scale/results.json",
            "results": scale_data,
        }
    else:
        scale_section = {
            "status": "pending",
            "context": "context missing in reports/scale/results.json",
            "source_file": "reports/scale/results.json",
            "results": None,
        }

    # 6. Edge
    edge_file = reports_dir / "edge" / "edge.json"
    energy_file = reports_dir / "edge" / "energy.json"
    edge_data = _load_json(edge_file)
    energy_data = _load_json(energy_file)

    if edge_data is not None:
        edge_section = {
            "status": "ok",
            "context": edge_data.get("context", "context missing in reports/edge/edge.json"),
            "source_file": "reports/edge/edge.json",
            "label": edge_data.get("label", "host-measured estimate"),
            "metrics": edge_data,
            "energy": energy_data,
        }
    else:
        edge_section = {
            "status": "pending",
            "context": "context missing in reports/edge/edge.json",
            "source_file": "reports/edge/edge.json",
            "label": "estimated",
            "metrics": None,
            "energy": None,
        }

    return {
        "detection": detection_section,
        "genuine_events": genuine_section,
        "drift": drift_section,
        "hadisd": hadisd_section,
        "scale": scale_section,
        "edge": edge_section,
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

        all_ts = []
        for r_deque in state.raw_rows.values():
            if r_deque:
                all_ts.append(r_deque[-1].get("ts_utc"))
        for v in latest_verdicts.values():
            if v.get("ts_utc"):
                all_ts.append(v.get("ts_utc"))
        if state.live_ingest_time:
            all_ts.append(state.live_ingest_time)

        valid_ts = [t for t in all_ts if t]
        system_latest_ts = max(valid_ts) if valid_ts else None

        stations = []
        for sid, meta in state.registry.items():
            lv = latest_verdicts.get(sid, {})
            raw_deque = state.raw_rows.get(sid)
            last_raw_ts = raw_deque[-1].get("ts_utc") if raw_deque else None
            last_v_ts = lv.get("ts_utc")
            last_seen_utc = last_raw_ts or last_v_ts

            cadence_min = None
            if meta.get("cadence_min"):
                try:
                    cadence_min = float(meta["cadence_min"])
                except (ValueError, TypeError):
                    pass

            if cadence_min is None and raw_deque and len(raw_deque) >= 2:
                gaps = []
                for i in range(1, len(raw_deque)):
                    t1_str = raw_deque[i - 1].get("ts_utc")
                    t2_str = raw_deque[i].get("ts_utc")
                    if t1_str and t2_str:
                        try:
                            dt1 = datetime.fromisoformat(t1_str.replace("Z", "+00:00"))
                            dt2 = datetime.fromisoformat(t2_str.replace("Z", "+00:00"))
                            diff_min = (dt2 - dt1).total_seconds() / 60.0
                            if diff_min > 0:
                                gaps.append(diff_min)
                        except Exception:
                            pass
                if gaps:
                    from statistics import median
                    cadence_min = float(median(gaps))

            if cadence_min is None or cadence_min <= 0:
                cadence_min = 180.0

            threshold_seconds = max(2.0 * cadence_min, 360.0) * 60.0

            is_offline = False
            if last_seen_utc is None:
                is_offline = True
            elif system_latest_ts:
                try:
                    t_last = datetime.fromisoformat(last_seen_utc.replace("Z", "+00:00"))
                    t_sys = datetime.fromisoformat(system_latest_ts.replace("Z", "+00:00"))
                    is_offline = (t_sys - t_last).total_seconds() > threshold_seconds
                except Exception:
                    is_offline = False

            label_val = "offline" if is_offline else lv.get("label", "normal")

            is_storm = any(
                sid in evt.get("affected_stations", [])
                for evt in state.active_events
                if evt.get("hours_done", 0.0) < evt.get("duration_hours", 1.0)
            )
            is_genuine = (lv.get("genuine_event", False) or is_storm) if not is_offline else False

            stations.append({
                "id": sid,
                "name": meta.get("name") or f"AWS {sid}",
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
                "elevation": meta.get("elevation", 0.0),
                "latest_label": label_val,
                "status": label_val,
                "genuine_event": is_genuine,
                "latest_ts": last_seen_utc,
                "last_seen_utc": last_seen_utc,
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
                "genuine_event": bool(v.get("genuine_event", False) or r.get("genuine_event", False)),
                "injected": bool(r.get("injected", False)),
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
        elif preset == "radiation":
            # Mungeshpur Radiation / shield heating fault: daytime warm bias for 3 simulated days
            sid = payload.get("station_id", "INI0001")
            inj = {
                "station_id": sid,
                "variable": "T",
                "root_cause": "radiation",
                "magnitude": 5.0,
                "duration_hours": 72.0,  # 3 simulated days
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
        return build_benchmark_report(REPORTS_DIR)

    return app

