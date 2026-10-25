"""
tests/bottom_engine/test_exchange_exit.py
TradingEngine._resolve_exchange_exit — 포지션 0 감지 시 청산 사유·체결가·청산 기준가 판정 6건.
YONA Algo SL·Trailing 발동 → ("SL", actualPrice, triggerPrice), 미발동 → ("LIQD", mark, 0.0).
"""
import pytest

from bottom_engine.engine_core import trading_engine
from bottom_engine.engine_core.trading_engine import TradingEngine


class _AlgoClient:
    """get_algo_order 응답을 순서대로 돌려주는 조회 전용 대역."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[str] = []

    def get_algo_order(self, algo_id: str):
        self.calls.append(algo_id)
        return self._responses.pop(0) if self._responses else None


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr(trading_engine, "_ALGO_STATUS_RETRY_SEC", 0.0)


def test_finished_uses_actual_price_and_trigger():
    """발동·체결 완료(FINISHED) → SL + 실제 평균 체결가 + 발동가."""
    c = _AlgoClient([{"algoStatus": "FINISHED", "actualPrice": "99.5", "triggerPrice": "100.0"}])
    assert TradingEngine._resolve_exchange_exit(c, "7", 100.2) == ("SL", 99.5, 100.0)
    assert c.calls == ["7"]


def test_triggered_without_price_falls_back_to_mark():
    """발동됐지만 actualPrice 0·triggerPrice 없음 → SL + mark, 기준가 0.0(미상)."""
    c = _AlgoClient([{"algoStatus": "TRIGGERED", "actualPrice": "0"}])
    assert TradingEngine._resolve_exchange_exit(c, "7", 100.0) == ("SL", 100.0, 0.0)


def test_canceled_is_external_liquidation():
    """YONA 주문이 취소 상태 → 발동 아님(LIQD), 재조회 없음."""
    c = _AlgoClient([{"algoStatus": "CANCELED", "actualPrice": "0", "triggerPrice": "100.0"}])
    assert TradingEngine._resolve_exchange_exit(c, "7", 100.0) == ("LIQD", 100.0, 0.0)
    assert c.calls == ["7"]


def test_lagging_new_then_finished_retries_once():
    """조회 반영 지연(NEW) → 1회 재조회 후 FINISHED면 SL."""
    c = _AlgoClient([{"algoStatus": "NEW"},
                     {"algoStatus": "FINISHED", "actualPrice": "101.25", "triggerPrice": "101.3"}])
    assert TradingEngine._resolve_exchange_exit(c, "7", 100.0) == ("SL", 101.25, 101.3)
    assert c.calls == ["7", "7"]


def test_query_failure_twice_is_liqd():
    """조회 실패(-2013 지연 등) 2회 → LIQD + mark."""
    c = _AlgoClient([None, None])
    assert TradingEngine._resolve_exchange_exit(c, "7", 100.0) == ("LIQD", 100.0, 0.0)
    assert c.calls == ["7", "7"]


def test_no_algo_id_skips_query():
    """등록된 SL ID 없음 → 조회 없이 LIQD."""
    c = _AlgoClient([])
    assert TradingEngine._resolve_exchange_exit(c, "", 100.0) == ("LIQD", 100.0, 0.0)
    assert c.calls == []
