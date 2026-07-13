import pytest

from mns.trading.execution_engine import ExecutionEngine
from mns.trading.qmt_adapter import QMTTradingAdapter
from mns.trading.tick_risk_engine import TickRiskEngine


def test_live_trading_paths_are_disabled():
    with pytest.raises(RuntimeError, match="disabled"):
        QMTTradingAdapter().place_order()
    with pytest.raises(RuntimeError, match="reserved"):
        TickRiskEngine().start()
    with pytest.raises(RuntimeError, match="disabled"):
        ExecutionEngine().submit()
