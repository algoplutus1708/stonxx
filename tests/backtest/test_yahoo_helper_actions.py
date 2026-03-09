import pandas as pd

from lumibot.tools.yahoo_helper import YahooHelper


def test_get_symbol_actions_uses_symbol_data(monkeypatch):
    idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02"])
    sample = pd.DataFrame(
        {
            "Dividends": [0.0, 0.5],
            "Stock Splits": [0.0, 0.0],
        },
        index=idx,
    )

    monkeypatch.setattr(YahooHelper, "get_symbol_data", staticmethod(lambda symbol, caching=True: sample))
    actions = YahooHelper.get_symbol_actions("AAPL", caching=True)

    assert list(actions.columns) == ["Dividends", "Stock Splits"]
    assert len(actions) == 1
    assert actions.iloc[0]["Dividends"] == 0.5
    assert actions.iloc[0]["Stock Splits"] == 0.0


def test_get_symbols_actions_uses_symbols_data(monkeypatch):
    idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02"])
    payload = {
        "AAPL": pd.DataFrame(
            {
                "Dividends": [0.0, 0.25],
                "Stock Splits": [0.0, 0.0],
            },
            index=idx,
        ),
        "MSFT": pd.DataFrame(
            {
                "Dividends": [0.0, 0.0],
                "Stock Splits": [0.0, 2.0],
            },
            index=idx,
        ),
    }

    monkeypatch.setattr(YahooHelper, "get_symbols_data", staticmethod(lambda symbols, caching=True: payload))
    actions = YahooHelper.get_symbols_actions(["AAPL", "MSFT"], caching=True)

    assert set(actions.keys()) == {"AAPL", "MSFT"}
    assert len(actions["AAPL"]) == 1
    assert len(actions["MSFT"]) == 1
    assert actions["AAPL"].iloc[0]["Dividends"] == 0.25
    assert actions["MSFT"].iloc[0]["Stock Splits"] == 2.0
