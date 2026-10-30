"""
tests/bottom_engine/test_onboard_date.py
HistoricalDataLoader.load_onboard_date — 백테스트 common_new 상장일수 원본(exchangeInfo onboardDate) 4건.
실거래 data_manager._days_since_listing과 같은 원본·정의: (판정 시각 − onboardDate) // 1일, 미상이면 9999.
"""
import pytest

import bottom_engine.backtest.historical_data_loader as _hdl
from bottom_engine.backtest.historical_data_loader import HistoricalDataLoader
from middle.data import data_manager as _dm

_INFO = {"symbols": [{"symbol": "AUSDT", "onboardDate": 1_700_000_000_000},
                     {"symbol": "BUSDT"}]}


@pytest.fixture()
def fetch(monkeypatch):
    """exchangeInfo 응답 대역 — 호출 횟수 기록, 네트워크·대기 없음."""
    calls = []
    monkeypatch.setattr(_hdl, "_onboard_map", None)
    monkeypatch.setattr(_hdl.time, "sleep", lambda _s: None)

    def _set(resp):
        monkeypatch.setattr(_hdl, "_fetch_url", lambda url: calls.append(url) or resp)
        return calls
    return _set


def test_known_symbol_and_reuse(fetch):
    """onboardDate 반환, exchangeInfo는 프로세스당 1회만 조회."""
    calls = fetch(_INFO)
    assert HistoricalDataLoader.load_onboard_date("AUSDT") == 1_700_000_000_000
    assert HistoricalDataLoader.load_onboard_date("AUSDT") == 1_700_000_000_000
    assert len(calls) == 1 and calls[0].endswith("/fapi/v1/exchangeInfo")


def test_unknown_or_missing_onboard_is_zero(fetch):
    """심볼 없음·onboardDate 없음 → 0 (호출처에서 9999 = 차단 없음, 실거래와 동일)."""
    fetch(_INFO)
    assert HistoricalDataLoader.load_onboard_date("ZUSDT") == 0
    assert HistoricalDataLoader.load_onboard_date("BUSDT") == 0


def test_fetch_failure_is_zero_and_not_cached(fetch):
    """조회 실패 → 0, 실패 결과는 저장하지 않아 다음 호출에서 재조회."""
    calls = fetch(None)
    assert HistoricalDataLoader.load_onboard_date("AUSDT") == 0
    assert len(calls) == _hdl._PAGE_RETRY
    assert _hdl._onboard_map is None


def test_days_definition_matches_live(monkeypatch):
    """백테스트 식 (봉 마감 − onboard) // 1일 == 실거래 _days_since_listing (같은 시각 기준)."""
    onboard = 1_700_000_000_000
    day = 86_400_000
    for close_time in (onboard, onboard + day - 1, onboard + day, onboard + 14 * day - 1, onboard + 14 * day):
        monkeypatch.setattr(_dm.time, "time", lambda ct=close_time: ct / 1000)
        assert max(0, (close_time - onboard) // day) == _dm._days_since_listing(onboard)
