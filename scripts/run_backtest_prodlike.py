#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        env[key] = value
    return env


def _bool_str(v: bool) -> str:
    return "true" if v else "false"


def find_latest_artifacts(log_dir: Path, started_at: float) -> tuple[Path | None, str | None]:
    candidates = []
    for p in log_dir.glob("*_tearsheet.html"):
        try:
            if p.stat().st_mtime >= started_at - 1.0:
                candidates.append(p)
        except FileNotFoundError:
            continue
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    prefix = latest.name.removesuffix("_tearsheet.html")
    return latest, prefix


def count_queue_submits(log_csv: Path) -> int | None:
    try:
        with log_csv.open("r", errors="replace") as f:
            return sum(1 for line in f if "Submitted to queue" in line)
    except FileNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a LumiBot backtest with prod-like flags using env from botspot_node/.env-local without printing secrets")
    parser.add_argument("--main", required=True, help="Path to extracted strategy main.py")
    parser.add_argument("--start", required=True, help="BACKTESTING_START (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="BACKTESTING_END (YYYY-MM-DD)")
    parser.add_argument(
        "--dotenv",
        default="/Users/robertgrzesik/Documents/Development/botspot_node/.env-local",
        help="dotenv file containing DATADOWNLOADER + S3 cache creds",
    )
    parser.add_argument(
        "--strategy-library",
        default="/Users/robertgrzesik/Documents/Development/Strategy Library",
        help="Working directory so artifacts land in Strategy Library/logs",
    )
    parser.add_argument(
        "--lumibot-root",
        default="/Users/robertgrzesik/Documents/Development/lumivest_bot_server/strategies/lumibot",
        help="Local lumibot repo root to add to PYTHONPATH",
    )
    parser.add_argument(
        "--cache-folder",
        default=None,
        help="Override LUMIBOT_CACHE_FOLDER (simulate fresh ECS task cache)",
    )
    parser.add_argument(
        "--cache-version",
        default=None,
        help="Override LUMIBOT_CACHE_S3_VERSION (use fresh namespace without deleting existing S3)",
    )
    parser.add_argument(
        "--cache-prefix",
        default=None,
        help="Override LUMIBOT_CACHE_S3_PREFIX (alternative to cache-version)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Label printed in output (no functional impact)",
    )
    parser.add_argument(
        "--subprocess-log",
        default=None,
        help="Write the child backtest process stdout/stderr to this file (keeps runner output small)",
    )

    args = parser.parse_args()

    main_py = Path(args.main).resolve()
    if not main_py.exists():
        raise SystemExit(f"main.py not found: {main_py}")

    dotenv_path = Path(args.dotenv)
    dotenv = load_dotenv(dotenv_path)

    strategy_library_root = Path(args.strategy_library).resolve()
    log_dir = strategy_library_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()

    # Ensure we use local lumibot source
    lumibot_root = str(Path(args.lumibot_root).resolve())
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = lumibot_root if not existing_pythonpath else f"{lumibot_root}:{existing_pythonpath}"

    # Backtest wiring / prod-like flags
    env["IS_BACKTESTING"] = "True"
    env["BACKTESTING_DATA_SOURCE"] = "thetadata"
    env["BACKTESTING_START"] = args.start
    env["BACKTESTING_END"] = args.end

    env["SHOW_PLOT"] = "True"
    env["SHOW_INDICATORS"] = "True"
    env["SHOW_TEARSHEET"] = "True"
    env["BACKTESTING_QUIET_LOGS"] = "false"
    env["BACKTESTING_SHOW_PROGRESS_BAR"] = "true"

    # Data downloader config
    for k in [
        "DATADOWNLOADER_BASE_URL",
        "DATADOWNLOADER_API_KEY",
        "DATADOWNLOADER_API_KEY_HEADER",
        "DATADOWNLOADER_SKIP_LOCAL_START",
    ]:
        if k in dotenv:
            env[k] = dotenv[k]

    # S3 cache backend config
    for k in [
        "LUMIBOT_CACHE_BACKEND",
        "LUMIBOT_CACHE_MODE",
        "LUMIBOT_CACHE_S3_BUCKET",
        "LUMIBOT_CACHE_S3_PREFIX",
        "LUMIBOT_CACHE_S3_REGION",
        "LUMIBOT_CACHE_S3_ACCESS_KEY_ID",
        "LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY",
        "LUMIBOT_CACHE_S3_SESSION_TOKEN",
        "LUMIBOT_CACHE_S3_VERSION",
    ]:
        if k in dotenv:
            env[k] = dotenv[k]

    if args.cache_folder:
        env["LUMIBOT_CACHE_FOLDER"] = args.cache_folder
        Path(args.cache_folder).mkdir(parents=True, exist_ok=True)

    if args.cache_version:
        env["LUMIBOT_CACHE_S3_VERSION"] = args.cache_version

    if args.cache_prefix:
        env["LUMIBOT_CACHE_S3_PREFIX"] = args.cache_prefix

    label = args.label or main_py.parent.name

    started_at = time.time()
    print(f"[run] label={label}")
    print(f"[run] main={main_py}")
    print(f"[run] window={args.start} -> {args.end}")
    print(f"[run] strategy_library={strategy_library_root}")
    print(f"[run] cache_folder={env.get('LUMIBOT_CACHE_FOLDER')}")
    print(f"[run] cache_s3_bucket={env.get('LUMIBOT_CACHE_S3_BUCKET')}")
    print(f"[run] cache_s3_prefix={env.get('LUMIBOT_CACHE_S3_PREFIX')}")
    print(f"[run] cache_s3_version={env.get('LUMIBOT_CACHE_S3_VERSION')}")

    subprocess_log = Path(args.subprocess_log) if args.subprocess_log else (strategy_library_root / f"subprocess_{label}.log")
    subprocess_log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[run] subprocess_log={subprocess_log}")

    with subprocess_log.open("w") as log_f:
        proc = subprocess.run(
            [sys.executable, str(main_py)],
            cwd=str(strategy_library_root),
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )

    elapsed_s = time.time() - started_at
    print(f"[run] exit_code={proc.returncode} elapsed_s={elapsed_s:.1f}")

    tearsheet, prefix = find_latest_artifacts(log_dir, started_at)
    if tearsheet and prefix:
        print(f"[artifacts] tearsheet={tearsheet}")
        trades = log_dir / f"{prefix}_trades.csv"
        logs = log_dir / f"{prefix}_logs.csv"
        settings = log_dir / f"{prefix}_settings.json"
        print(f"[artifacts] trades={trades if trades.exists() else '(missing)'}")
        print(f"[artifacts] logs={logs if logs.exists() else '(missing)'}")
        print(f"[artifacts] settings={settings if settings.exists() else '(missing)'}")
        submits = count_queue_submits(logs)
        if submits is not None:
            print(f"[metrics] queue_submits={submits}")

    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
