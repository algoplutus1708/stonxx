def tearsheet_custom_metrics
============================

``tearsheet_custom_metrics`` is a strategy lifecycle hook that runs during backtest
analysis, immediately before LumiBot writes:

- ``*_tearsheet.html``
- ``*_tearsheet_metrics.json``

Use this hook when you want strategy-defined metrics in both artifacts.

When it runs
------------

1. Backtest trading completes.
2. LumiBot computes strategy/benchmark return series and drawdown context.
3. LumiBot calls ``tearsheet_custom_metrics(...)``.
4. Returned metrics are appended to the tearsheet metrics table and JSON scalar metrics.

Method signature
----------------

.. code-block:: python

    def tearsheet_custom_metrics(
        self,
        stats_df: pd.DataFrame | None,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series | None,
        drawdown: pd.Series,
        drawdown_details: pd.DataFrame,
        risk_free_rate: float,
    ) -> dict:
        ...

Parameter structure
-------------------

``stats_df`` (``pd.DataFrame | None``)
  Backtest stats dataframe (same data used for ``*_stats.csv/parquet``).

``strategy_returns`` (``pd.Series``)
  Strategy return series used for tearsheet metric calculations.

``benchmark_returns`` (``pd.Series | None``)
  Benchmark return series when a benchmark is available; otherwise ``None``.

``drawdown`` (``pd.Series``)
  Strategy drawdown series derived from cumulative returns.

``drawdown_details`` (``pd.DataFrame``)
  Drawdown periods table (columns such as start/end/valley/days/max drawdown when available).

``risk_free_rate`` (``float``)
  Effective risk-free rate used by tearsheet metrics.

Return format
-------------

Return a ``dict`` mapping metric names to values.

Supported formats:

.. code-block:: python

    {"Custom Metric A": 1.23}
    {"Custom Metric B": {"strategy": 1.23, "benchmark": 0.91}}

Behavior rules:

1. Return ``{}`` if no custom metrics apply.
2. Returning ``None`` is treated as no custom metrics.
3. Returning a non-dict is ignored (with a warning).
4. Exceptions inside the hook are caught; tearsheet generation continues.

Example
-------

.. code-block:: python

    class MyStrategy(Strategy):
        def tearsheet_custom_metrics(
            self,
            stats_df,
            strategy_returns,
            benchmark_returns,
            drawdown,
            drawdown_details,
            risk_free_rate,
        ):
            if strategy_returns.empty:
                return {}

            p95 = float(strategy_returns.quantile(0.95))
            avg_dd_days = (
                float(drawdown_details["days"].mean())
                if not drawdown_details.empty and "days" in drawdown_details.columns
                else 0.0
            )

            return {
                "95th Percentile Daily Return": p95,
                "Average Drawdown Days": avg_dd_days,
            }

API reference (source of truth)
-------------------------------

The method docstring below is auto-loaded from the Strategy class and should be
treated as the canonical API reference.

.. automethod:: lumibot.strategies.strategy.Strategy.tearsheet_custom_metrics
