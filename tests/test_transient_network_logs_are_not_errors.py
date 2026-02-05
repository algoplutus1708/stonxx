import logging
from types import SimpleNamespace

from lumibot.brokers.tradier import Tradier
from lumibot.strategies._strategy import _Strategy


def test_update_broker_balances_exception_logs_info(monkeypatch, caplog):
    def raise_balance_error(_quote_asset, _strategy):
        raise ConnectionError("Remote end closed connection without response")

    dummy = SimpleNamespace(
        is_backtesting=False,
        last_broker_balances_update=None,
        _quote_asset=None,
        broker=SimpleNamespace(_get_balances_at_broker=raise_balance_error),
        logger=logging.getLogger("tests.broker_balances"),
    )

    caplog.set_level(logging.DEBUG)
    result = _Strategy.update_broker_balances(dummy, force_update=True)

    assert result is False
    assert any(
        record.levelno == logging.INFO and "Error getting broker balances" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.INFO
        and "Error getting broker balances" in record.getMessage()
        and record.exc_info
        for record in caplog.records
    )
    assert all(record.levelno < logging.ERROR for record in caplog.records)


def test_tradier_pull_orders_exception_logs_info(monkeypatch, caplog):
    def raise_orders_error():
        raise ConnectionError("Max retries exceeded")

    dummy = SimpleNamespace(
        tradier=SimpleNamespace(
            orders=SimpleNamespace(get_orders=raise_orders_error),
        )
    )

    caplog.set_level(logging.DEBUG)
    result = Tradier._pull_broker_all_orders(dummy)

    assert result == []
    assert any(
        record.levelno == logging.INFO and "Error pulling orders from Tradier" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.INFO
        and "Error pulling orders from Tradier" in record.getMessage()
        and record.exc_info
        for record in caplog.records
    )
    assert all(record.levelno < logging.ERROR for record in caplog.records)
