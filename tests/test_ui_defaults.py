import inspect

import pandas as pd


def test_strategy_backtest_ui_defaults_are_true() -> None:
    """Guardrail: end-user defaults must keep UI output enabled.

    Acceptance/CI backtests explicitly disable UI via env vars. That MUST NOT leak into normal
    defaults — callers should still get plots/indicators/tearsheets by default.
    """
    from lumibot.strategies.strategy import Strategy

    sig = inspect.signature(Strategy.backtest)
    assert sig.parameters["show_plot"].default is True
    assert sig.parameters["show_tearsheet"].default is True
    assert sig.parameters["show_indicators"].default is True


def test_lumibot_disable_ui_prevents_browser_open(monkeypatch, tmp_path) -> None:
    """Guardrail: acceptance backtests must not open browser windows."""
    from lumibot.tools import indicators as indicators_mod

    monkeypatch.setenv("LUMIBOT_DISABLE_UI", "true")

    def _should_not_open(_: str) -> None:
        raise AssertionError("webbrowser.open() must not be called when LUMIBOT_DISABLE_UI=true")

    monkeypatch.setattr(indicators_mod.webbrowser, "open", _should_not_open)

    def _fake_qs_html(*args, **kwargs):
        output = kwargs.get("output")
        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write("<html><body>stub</body></html>")
        return {"ok": True}

    monkeypatch.setattr(indicators_mod.qs.reports, "html", _fake_qs_html)

    idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    strategy_df = pd.DataFrame({"portfolio_value": [100.0, 101.0, 99.0]}, index=idx)
    benchmark_df = pd.DataFrame({"symbol_cumprod": [1.0, 1.01, 1.02]}, index=idx)

    indicators_mod.create_tearsheet(
        strategy_df=strategy_df,
        strat_name="TestStrategy",
        tearsheet_file=str(tmp_path / "tearsheet.html"),
        benchmark_df=benchmark_df,
        benchmark_asset="SPY",
        show_tearsheet=True,
        save_tearsheet=True,
        risk_free_rate=0.0,
    )
