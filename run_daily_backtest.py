"""Compatibility wrapper for the stonxx daily backtest runner.

This keeps the shorter `python run_daily_backtest.py` command working while
reusing the existing backtest implementation in `run_stonxx_backtest.py`.
"""

from run_stonxx_backtest import run_backtest as _run_stonxx_backtest


def run_backtest():
    return _run_stonxx_backtest()


if __name__ == "__main__":
    run_backtest()
