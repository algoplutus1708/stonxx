"""
CI acceptance backtests (ThetaData) — runs the *same 7 demo scripts* we use locally.

User requirement (non-negotiable):
- These tests must execute the *same 7* Strategy Library acceptance demos (copied verbatim into
  `tests/backtest/acceptance_strategies/`) in a subprocess, with the same prod-like env flags.
- They must FAIL if any run tries to enqueue a ThetaData downloader request (cache miss / fallback).

Implementation notes:
- We run each script in an isolated temp working directory so that `logs/` is clean and parseable.
- We parse the generated `*_tearsheet.csv` for Total Return / CAGR% / Max Drawdown and assert
  broad guardrail ranges (not exact values).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

pytestmark = [pytest.mark.acceptance_backtest]


# Emitted by lumibot/tools/thetadata_queue_client.py when a request is enqueued to ThetaTerminal.
_DOWNLOADER_QUEUE_LOG_PATTERNS = (
    r"Submitted to queue:\s+request_id=",
    r"\[THETA\]\[QUEUE\]\s+Submitted",
    r"ThetaData cache MISS .* fetching .* from ThetaTerminal",
)


def _is_ci() -> bool:
    return (os.environ.get("GITHUB_ACTIONS", "").lower() == "true") or bool(os.environ.get("CI"))


def _require_env(keys: list[str]) -> None:
    missing = [k for k in keys if not os.environ.get(k)]
    if not missing:
        return
    message = f"Missing required env vars for acceptance backtests: {missing}"
    if _is_ci():
        pytest.fail(message)
    pytest.skip(message)


def _parse_percent(text: str) -> float:
    """
    Parse values like:
    - "-17%" -> -0.17
    - "48.86%" -> 0.4886
    - "8,272%" -> 82.72
    """
    s = str(text).strip()
    if not s.endswith("%"):
        raise ValueError(f"Expected percent string, got {text!r}")
    s = s[:-1].replace(",", "").strip()
    return float(s) / 100.0


def _read_tearsheet_metrics(tearsheet_csv: Path) -> dict[str, float]:
    df = pd.read_csv(tearsheet_csv)
    if "Metric" not in df.columns or "Strategy" not in df.columns:
        raise AssertionError(f"Unexpected tearsheet CSV columns: {list(df.columns)}")

    def _get(metric_name: str) -> float:
        row = df.loc[df["Metric"] == metric_name]
        if row.empty:
            raise AssertionError(f"Missing metric {metric_name!r} in {tearsheet_csv}")
        return _parse_percent(row["Strategy"].iloc[0])

    return {
        "total_return": _get("Total Return"),
        "cagr": _get("CAGR% (Annual Return)"),
        "max_drawdown": _get("Max Drawdown"),
    }


def _find_single(paths: list[Path], description: str) -> Path:
    if len(paths) != 1:
        raise AssertionError(f"Expected exactly 1 {description}, found {len(paths)}: {[p.name for p in paths]}")
    return paths[0]


def _file_contains_any(path: Path, patterns: tuple[str, ...]) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return None
    for pattern in patterns:
        if re.search(pattern, text):
            return pattern
    return None


def _assert_no_downloader_queue_used(run_dir: Path) -> None:
    logs_dir = run_dir / "logs"
    candidates = list(logs_dir.glob("*_logs.csv"))
    log_csv = candidates[0] if len(candidates) == 1 else None

    pattern = None
    if log_csv is not None:
        pattern = _file_contains_any(log_csv, _DOWNLOADER_QUEUE_LOG_PATTERNS)

    # Also scan subprocess stdout/stderr (best-effort) in case logging isn't written.
    if pattern is None:
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        pattern = _file_contains_any(stdout_path, _DOWNLOADER_QUEUE_LOG_PATTERNS) or _file_contains_any(
            stderr_path, _DOWNLOADER_QUEUE_LOG_PATTERNS
        )

    if pattern is not None:
        raise AssertionError(
            "Acceptance backtest attempted to use the ThetaData downloader queue "
            f"(pattern {pattern!r} matched). Expected fully-warm S3 cache (no downloader queue usage)."
        )


def _base_env(repo_root: Path) -> dict[str, str]:
    required = [
        "DATADOWNLOADER_BASE_URL",
        "DATADOWNLOADER_API_KEY",
        "LUMIBOT_CACHE_BACKEND",
        "LUMIBOT_CACHE_MODE",
        "LUMIBOT_CACHE_S3_BUCKET",
        "LUMIBOT_CACHE_S3_PREFIX",
        "LUMIBOT_CACHE_S3_REGION",
        "LUMIBOT_CACHE_S3_VERSION",
        "LUMIBOT_CACHE_S3_ACCESS_KEY_ID",
        "LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY",
        # ThetaData credentials are required by Strategy.backtest() input validation even when
        # using the remote downloader. Any non-empty values are sufficient here.
        "THETADATA_USERNAME",
        "THETADATA_PASSWORD",
    ]
    _require_env(required)

    env = dict(os.environ)
    env.update(
        {
            "IS_BACKTESTING": "True",
            "BACKTESTING_DATA_SOURCE": "thetadata",
            "SHOW_PLOT": "True",
            "SHOW_INDICATORS": "True",
            "SHOW_TEARSHEET": "True",
            "BACKTESTING_QUIET_LOGS": "false",
            "BACKTESTING_SHOW_PROGRESS_BAR": "true",
            "SAVE_LOGFILE": env.get("SAVE_LOGFILE", "true"),
        }
    )

    # Ensure we always import the checked-out source tree (even when running in a temp cwd).
    env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}".strip(":")
    return env


@dataclass(frozen=True)
class _RunCase:
    slug: str
    strategy_name: str
    script_filename: str
    start_date: str
    end_date: str
    data_source: str = "thetadata"
    expected_total_return: float | None = None
    expected_cagr: float | None = None
    expected_max_drawdown: float | None = None
    tol_total_return: float = 0.30
    tol_cagr: float = 0.10
    tol_max_drawdown: float = 0.15


def _run_script(case: _RunCase, tmp_path: Path, run_name: str) -> tuple[Path, dict[str, float]]:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "tests" / "backtest" / "acceptance_strategies" / case.script_filename
    assert script_path.exists(), f"Missing strategy script: {script_path}"

    run_dir = tmp_path / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    env = _base_env(repo_root)
    env["BACKTESTING_START"] = case.start_date
    env["BACKTESTING_END"] = case.end_date
    env["BACKTESTING_DATA_SOURCE"] = case.data_source

    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    # CI runners can be slow; still apply an upper bound so jobs don't hang forever.
    timeout_s = 60 * 90  # 90 minutes per run

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(run_dir),
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=timeout_s,
        )

    if proc.returncode != 0:
        tail = ""
        try:
            tail = (stderr_path.read_text(errors="ignore") + "\n" + stdout_path.read_text(errors="ignore"))[-8000:]
        except Exception:
            tail = "(failed to read stdout/stderr tail)"
        raise AssertionError(f"{case.slug} failed (exit={proc.returncode}).\n--- tail ---\n{tail}")

    logs_dir = run_dir / "logs"
    settings = _find_single(
        sorted(logs_dir.glob(f"{case.strategy_name}_*_settings.json")),
        f"{case.strategy_name} settings.json",
    )
    tearsheet_csv = _find_single(
        sorted(logs_dir.glob(f"{case.strategy_name}_*_tearsheet.csv")),
        f"{case.strategy_name} tearsheet.csv",
    )

    # Artifact sanity
    _find_single(sorted(logs_dir.glob(f"{case.strategy_name}_*_trades.csv")), f"{case.strategy_name} trades.csv")

    _assert_no_downloader_queue_used(run_dir)

    metrics = _read_tearsheet_metrics(tearsheet_csv)

    def _assert_close(actual: float, expected: float | None, tol: float, label: str) -> None:
        if expected is None:
            return
        if abs(actual - expected) > tol:
            raise AssertionError(
                f"{case.slug} {label} out of range: actual={actual:.4f} expected={expected:.4f} tol=±{tol:.4f}\n"
                f"tearsheet={tearsheet_csv}"
            )

    _assert_close(metrics["total_return"], case.expected_total_return, case.tol_total_return, "total_return")
    _assert_close(metrics["cagr"], case.expected_cagr, case.tol_cagr, "cagr")
    _assert_close(metrics["max_drawdown"], case.expected_max_drawdown, case.tol_max_drawdown, "max_drawdown")

    # Also sanity-check that settings.json is parseable (helps detect truncated writes).
    try:
        json.loads(settings.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AssertionError(f"{case.slug} produced an invalid settings.json: {settings}") from exc

    return run_dir, metrics


def test_acceptance_aapl_deep_dip_calls(tmp_path: Path) -> None:
    case = _RunCase(
        slug="aapl_deep_dip_calls",
        strategy_name="AAPLDeepDipCalls",
        script_filename="AAPL Deep Dip Calls (Copy 4).py",
        start_date="2020-01-01",
        end_date="2025-12-01",
        expected_total_return=8.70,
        expected_cagr=0.4886,
        expected_max_drawdown=-0.3409,
        tol_total_return=1.50,
        tol_cagr=0.15,
        tol_max_drawdown=0.15,
    )
    _run_script(case, tmp_path, "aapl_deep_dip_calls")


def test_acceptance_leaps_alpha_picks(tmp_path: Path) -> None:
    # Short window: must trade UBER/CLS/MFC (both legs). Metrics are annualized, so keep loose.
    short = _RunCase(
        slug="leaps_alpha_picks_short",
        strategy_name="LeapsCallDebitSpread",
        script_filename="Leaps Buy Hold (Alpha Picks).py",
        start_date="2025-10-01",
        end_date="2025-10-15",
        expected_max_drawdown=-0.0142,
        tol_max_drawdown=0.05,
    )
    run_dir, _ = _run_script(short, tmp_path, "leaps_short")

    # Verify required tickers traded (both legs show up in trades.csv).
    trades_csv = _find_single(
        sorted((run_dir / "logs").glob("LeapsCallDebitSpread_*_trades.csv")),
        "Leaps trades.csv",
    )
    trades = pd.read_csv(trades_csv)
    symbols = set(str(s).upper() for s in trades.get("symbol", pd.Series(dtype=str)).dropna().tolist())
    for required in ("UBER", "CLS", "MFC"):
        assert required in symbols, f"Expected {required} to be traded in short window; got symbols={sorted(symbols)[:25]}"

    # Full-year window (guardrail metrics from docs).
    full_year = _RunCase(
        slug="leaps_alpha_picks_full_year",
        strategy_name="LeapsCallDebitSpread",
        script_filename="Leaps Buy Hold (Alpha Picks).py",
        start_date="2025-01-01",
        end_date="2025-12-01",
        expected_total_return=-0.03,
        expected_cagr=-0.0303,
        expected_max_drawdown=-0.1933,
        tol_total_return=0.25,
        tol_cagr=0.15,
        tol_max_drawdown=0.15,
    )
    _run_script(full_year, tmp_path, "leaps_full_year")


def test_acceptance_tqqq_sma200(tmp_path: Path) -> None:
    base = _RunCase(
        slug="tqqq_sma200_thetadata",
        strategy_name="TqqqSma200Strategy",
        script_filename="TQQQ 200-Day MA.py",
        start_date="2013-01-01",
        end_date="2025-12-01",
        expected_total_return=82.72,
        expected_cagr=0.4094,
        expected_max_drawdown=-0.4882,
        tol_total_return=10.0,
        tol_cagr=0.15,
        tol_max_drawdown=0.15,
    )
    _, theta_metrics = _run_script(base, tmp_path, "tqqq_thetadata")

    yahoo = _RunCase(
        slug="tqqq_sma200_yahoo",
        strategy_name="TqqqSma200Strategy",
        script_filename="TQQQ 200-Day MA.py",
        start_date=base.start_date,
        end_date=base.end_date,
        data_source="yahoo",
        expected_total_return=82.72,
        expected_cagr=0.4094,
        expected_max_drawdown=-0.4882,
        tol_total_return=12.0,
        tol_cagr=0.20,
        tol_max_drawdown=0.20,
    )
    _, yahoo_metrics = _run_script(yahoo, tmp_path, "tqqq_yahoo")

    # Parity sanity: Yahoo and ThetaData should be directionally close (avoid obvious inflation).
    assert abs(theta_metrics["cagr"] - yahoo_metrics["cagr"]) < 0.10


def test_acceptance_backdoor_butterfly(tmp_path: Path) -> None:
    # Speed baseline window
    baseline = _RunCase(
        slug="backdoor_butterfly_baseline",
        strategy_name="BackdoorButterfly0DTE",
        script_filename="Backdoor Butterfly 0 DTE (Copy).py",
        start_date="2025-01-01",
        end_date="2025-11-30",
        expected_total_return=-0.20,
        expected_cagr=-0.21,
        expected_max_drawdown=-0.26,
        tol_total_return=0.30,
        tol_cagr=0.20,
        tol_max_drawdown=0.20,
    )
    _run_script(baseline, tmp_path, "backdoor_baseline")

    # Full-year acceptance window
    full_year = _RunCase(
        slug="backdoor_butterfly_full_year",
        strategy_name="BackdoorButterfly0DTE",
        script_filename="Backdoor Butterfly 0 DTE (Copy).py",
        start_date="2025-01-01",
        end_date="2025-12-01",
        expected_total_return=-0.20,
        expected_cagr=-0.21,
        expected_max_drawdown=-0.26,
        tol_total_return=0.35,
        tol_cagr=0.25,
        tol_max_drawdown=0.25,
    )
    _run_script(full_year, tmp_path, "backdoor_full_year")


def test_acceptance_meli_deep_drawdown(tmp_path: Path) -> None:
    case = _RunCase(
        slug="meli_deep_drawdown",
        strategy_name="MeliDeepDrawdownCalls",
        script_filename="Meli Deep Drawdown Calls.py",
        start_date="2013-01-01",
        end_date="2025-12-18",
        # Historical anchor (under investigation; keep very wide tolerances).
        expected_total_return=1.31,
        expected_cagr=0.0726,
        expected_max_drawdown=-0.9778,
        tol_total_return=3.00,
        tol_cagr=0.40,
        tol_max_drawdown=0.25,
    )
    _run_script(case, tmp_path, "meli_full")


def test_acceptance_backdoor_smartlimit(tmp_path: Path) -> None:
    case = _RunCase(
        slug="backdoor_smartlimit",
        strategy_name="BackdoorButterfly0DTESmartLimit",
        script_filename="Backdoor Butterfly 0 DTE (Copy) - with SMART LIMITS.py",
        start_date="2025-01-01",
        end_date="2025-12-01",
        expected_total_return=-0.03,
        expected_cagr=-0.03,
        expected_max_drawdown=-0.1358,
        tol_total_return=0.30,
        tol_cagr=0.25,
        tol_max_drawdown=0.20,
    )
    _run_script(case, tmp_path, "backdoor_smartlimit")


def test_acceptance_spx_short_straddle(tmp_path: Path) -> None:
    # Speed baseline
    baseline = _RunCase(
        slug="spx_short_straddle_baseline",
        strategy_name="SPXShortStraddle",
        script_filename="SPX Short Straddle Intraday (Copy).py",
        start_date="2025-01-01",
        end_date="2025-11-30",
        expected_total_return=-0.17,
        expected_cagr=-0.1899,
        expected_max_drawdown=-0.2834,
        tol_total_return=0.25,
        tol_cagr=0.20,
        tol_max_drawdown=0.20,
    )
    _run_script(baseline, tmp_path, "spx_baseline")

    # Stall repro / prod parity
    repro = _RunCase(
        slug="spx_short_straddle_repro",
        strategy_name="SPXShortStraddle",
        script_filename="SPX Short Straddle Intraday (Copy).py",
        start_date="2025-01-06",
        end_date="2025-12-26",
        expected_total_return=-0.17,
        expected_cagr=-0.1781,
        expected_max_drawdown=-0.3351,
        tol_total_return=0.30,
        tol_cagr=0.25,
        tol_max_drawdown=0.25,
    )
    _run_script(repro, tmp_path, "spx_repro")

