"""
tests/middle/test_ticker_keep.py
REST 시세 빈 응답 처리 (2026-11-16) — 네트워크 없이 대역.
 A 조회 실패(빈 응답)면 직전 시세 유지 → 1열 목록이 비지 않고, WS 복구 뒤 일부 종목 순위도 생기지 않음
 B 전체 REST 시세 1회 성공 전까지는 WS 수신 중에도 REST 재시도 (시작 시 REST 실패 대비)
"""
import inspect
import types

import middle.data.data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker
from bottom_engine.models import StrategyParams


def _t(sym, chg, vol):
    return SymbolTicker(sym, 100.0, 1.0, chg, vol, 101.0, 99.0)


_FULL = [_t(f"S{i}USDT", 10.0 - i * 0.1, 1e9 - i) for i in range(150)]


def _dm(monkeypatch):
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default", staticmethod(lambda m: StrategyParams(sort_mode=m)))
    dm = MiddleDataManager()
    dm._client._get_trading_symbols = lambda: {t.symbol for t in _FULL}
    return dm


def _sizes(dm):
    return (len(dm._tickers), len(dm._vol_rank), len(dm.get_all_ranked_by_change(100)), len(dm._sorted_tickers[:100]))


def test_empty_rest_response_keeps_previous_tickers(monkeypatch):
    dm = _dm(monkeypatch)
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: list(_FULL))
    dm._refresh_tickers()
    assert _sizes(dm) == (150, 150, 100, 100)
    seen = []
    dm._on_ranking_ready_cb = lambda: seen.append(1)
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: [])              # REST 실패 → 빈 응답
    dm._refresh_tickers()
    assert _sizes(dm) == (150, 150, 100, 100)                              # 수정 전: (0, 0, 0, 0)
    assert seen == []                                                      # 바뀐 것 없음 → 화면 갱신 콜백 없음


def test_ws_recovery_after_failure_updates_on_top_of_previous_list(monkeypatch):
    dm = _dm(monkeypatch)
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: list(_FULL))
    dm._refresh_tickers()
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: [])
    dm._refresh_tickers()
    dm._on_ws_ticker_update([_t("S120USDT", 25.0, 5e8), _t("S7USDT", 9.0, 2e8)])   # 바뀐 종목만 Push
    assert len(dm._tickers) == 150                                         # 수정 전: 2종목만 남음
    top = [r[0] for r in dm.get_all_ranked_by_change(100)]
    assert len(top) == 100 and top[0] == "S120USDT"                        # 새 값 반영, 나머지 유지


def test_full_load_flag_and_retry_condition(monkeypatch):
    dm = _dm(monkeypatch)
    assert dm._tickers_full_loaded is False
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: [])              # 시작 시 REST 실패
    dm._refresh_tickers()
    assert dm._tickers_full_loaded is False and dm._tickers == []
    dm._tkr_svc = types.SimpleNamespace(fetch_all=lambda: list(_FULL))
    dm._refresh_tickers()
    assert dm._tickers_full_loaded is True
    dm.stop_auto_refresh()
    assert dm._tickers_full_loaded is False                                # STOP → START 시 다시 전체 조회
    src = inspect.getsource(MiddleDataManager._auto_refresh_loop)
    # WS 수신 중이어도 전체 REST 1회 성공 전까지는 5초마다 REST 재시도 (차단 중 제외)
    assert "or not self._tickers_full_loaded" in src and "rate_gate.remaining() <= 0" in src
