"""One-command demo: starts API server, live replay engine, and opens dashboard. Owner: Person B.

Usage::
    python -m skyguard.demo [--scorer fake|real] [--speed N] [--replay heatwave|lastweek|synthetic] [--port P] [--no-browser]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
import webbrowser
import uvicorn


def check_models_exist() -> bool:
    models_dir = Path("models")
    if models_dir.exists() and models_dir.is_dir():
        files = list(models_dir.glob("*"))
        if any(f.suffix in (".pkl", ".onnx", ".bin", ".pt", ".json") for f in files):
            return True
    return False


def check_real_data_exists() -> bool:
    reg_file = Path("data/station_registry.csv")
    stream_dir = Path("data/stream")
    if reg_file.exists() and stream_dir.exists():
        parquets = list(stream_dir.glob("*.parquet"))
        jsonls = list(stream_dir.glob("*.jsonl"))
        if parquets or jsonls:
            return True
    return False


def check_live_data_exists() -> bool:
    stream_file = Path("data/stream/wis2_latest.jsonl")
    reg_file = Path("data/wis2/stations.csv")
    return stream_file.exists() and reg_file.exists()


def choose_scorer(scorer: str = "auto") -> str:
    """Pick the scorer for the demo server.

    The demo replays (synthetic stations, or live IMD WIS 2.0 IDs) are not stations the trained model
    has history or neighbours for, so on them it produces meaningless forecasts and false alarms.
    "auto" therefore uses the stand-in scorer; "real" is still available when asked for explicitly.
    """
    if scorer == "auto":
        if check_models_exist():
            print("NOTE: models/ contains a trained model, but the demo stations are not in its training "
                  "registry. Using the stand-in scorer; pass --scorer real to override.")
        return "fake"
    if scorer == "real":
        print("WARNING: --scorer real on demo/live stations: the model has no history or neighbours for "
              "these station IDs, so expect unreliable verdicts. Its measured results are on the "
              "Evaluation page.")
    return scorer


def run_demo(
    scorer: str = "auto",
    speed: float = 1800.0,
    replay: str = "synthetic",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    # 1. Determine scorer backend
    chosen_scorer = choose_scorer(scorer)

    os.environ["SKYGUARD_SCORER"] = chosen_scorer

    # 2. Determine replay source
    has_real_data = check_real_data_exists()
    has_live_data = check_live_data_exists()

    if replay == "live":
        if has_live_data:
            actual_replay = "live"
        else:
            print("WARNING: Live dataset files (data/stream/wis2_latest.jsonl and data/wis2/stations.csv) not found. Falling back to 'synthetic'.")
            actual_replay = "synthetic"
    elif replay in ("heatwave", "lastweek") and not has_real_data:
        print(f"WARNING: Real dataset for '{replay}' not found in data/stream/. Falling back to 'synthetic'.")
        actual_replay = "synthetic"
    else:
        actual_replay = replay

    os.environ["SKYGUARD_REPLAY_MODE"] = actual_replay

    print("=========================================================")
    print(" WeatherFox - Automated Quality Control System Demo")
    print("=========================================================")
    print(f"  - Scorer backend : {chosen_scorer.upper()} ({'Real ML models' if chosen_scorer == 'real' else 'Demo Fake Scorer'})")
    print(f"  - Replay mode    : {actual_replay}")
    print(f"  - Replay speed   : {speed}x real-time")
    print(f"  - Dashboard URL  : http://127.0.0.1:{port}")
    print("=========================================================")
    print()

    # Launch browser after slight delay if requested
    if open_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(f"http://127.0.0.1:{port}")
        
        import threading
        threading.Thread(target=_open, daemon=True).start()

    # Start uvicorn server serving FastAPI app
    from skyguard.api.main import create_app, state
    state.speed_factor = speed
    state.replay_mode = actual_replay

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    # Windows consoles default to cp1252; never crash on printing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="SkyGuard AI One-Command Demo")
    parser.add_argument("--scorer", choices=["auto", "fake", "real"], default="auto", help="Scorer backend")
    parser.add_argument("--speed", type=float, default=1800.0, help="Replay speed factor (e.g. 1800 = 1 hour / 2 sec)")
    parser.add_argument("--replay", choices=["synthetic", "heatwave", "lastweek", "live"], default="synthetic", help="Replay dataset")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    run_demo(
        scorer=args.scorer,
        speed=args.speed,
        replay=args.replay,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
