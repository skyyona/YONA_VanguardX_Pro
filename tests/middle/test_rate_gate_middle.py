"""
tests/middle/test_rate_gate_middle.py
중단 쪽 요청 몰림 줄이기 (2026-11-15) — 네트워크 없이 대역.
 4-1 주기 작업 겹침 방지 · 4-2 차단 중 갱신 묶음 즉시 종료 · 4-3 시작 후 STAGE3 첫 완료 뒤 예고 판정
 4-4 exchangeInfo 실패 뒤 60초 재조회 안 함 · 4-5 get_ohlcv 빈 결과 뒤 30초 재조회 안 함
"""
import inspect
import threading
import types

import core.rate_gate as rg
import middle.api.binance_client as bc
import middle.data.data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker


def _tkr(sym):
    return SymbolTicker(sym, 100.0, 1.0, 1.0, 1e6, 101.0, 99.0)


def test_periodic_job_skipped_while_previous_still_running():
    dm = MiddleDataManager()
    gate, started = threading.Event(), []

    def slow(tag):
        started.append(tag)
        gate.wait(5)
    dm._start_job("stage3", slow, "a")
    dm._start_job("stage3", slow, "b")          # 앞 실행 진행 중 → 건너뜀
    dm._start_job("stage2", slow, "c")          # 다른 작업은 시작
    for _ in range(200):
        if len(started) >= 2:
            break
        threading.Event().wait(0.01)
    assert sorted(started) == ["a", "c"]
    gate.set()
    for _ in range(200):
        if not dm._jobs_running:
            break
        threading.Event().wait(0.01)
    dm._start_job("stage3", lambda t: started.append(t), "d")   # 끝난 뒤에는 다시 시작
    for _ in range(200):
        if "d" in started:
            break
        threading.Event().wait(0.01)
    assert "d" in started


def test_blocked_gate_stops_stage_and_forecast_requests(monkeypatch):
    monkeypatch.setattr(rg, "remaining", lambda: 42.0)
    dm = MiddleDataManager()
    calls = []
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: calls.append(("k", s)) or [])
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: calls.append(("ls", s)))
    dm._oi_svc = types.SimpleNamespace(fetch_change_pct=lambda s: calls.append(("oi", s)),
                                       fetch_series=lambda s, p="5m", limit=290: calls.append(("ois", s)) or {})
    dm._client = types.SimpleNamespace(fetch_all_premium_index=lambda: [], fetch_funding_info=lambda: [])
    dm._sorted_tickers = [_tkr("AUSDT"), _tkr("BUSDT")]
    dm._refresh_topn_klines(2)
    dm._refresh_topn_scores(2)
    assert dm._forecast_one_safe("AUSDT", True) is None
    assert calls == []                          # 종목 조회 하나도 안 나감
    assert dm._stage3_done is True              # 묶음은 끝난 것으로 처리 (예고 시작 조건)


def test_forecast_waits_for_first_stage3_and_flag_resets_on_stop():
    dm = MiddleDataManager()
    assert dm._stage3_done is False
    src = inspect.getsource(MiddleDataManager._auto_refresh_loop)
    assert "self._stage3_done and self._forecast_due(" in src           # 첫 STAGE3 완료 전에는 예고 판정 안 함
    assert 'rate_gate.remaining() <= 0' in src                           # 차단 중 REST 시세 갱신 생략
    dm._stage3_done = True
    dm.stop_auto_refresh()
    assert dm._stage3_done is False


def test_exchange_info_failure_not_refetched_for_60s(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(bc.time, "time", lambda: now[0])
    cl = bc.MiddleBinanceClient()
    calls = []
    cl.fetch_exchange_info = lambda: calls.append(1)                   # 실패 (None)
    assert cl._get_trading_symbols() == set()
    for _ in range(5):                                                  # WS 1초 콜백 흉내
        now[0] += 1
        cl._get_trading_symbols()
    assert len(calls) == 1
    now[0] += bc._TRADING_RETRY_SEC
    cl.fetch_exchange_info = lambda: calls.append(1) or {"symbols": [{"symbol": "AUSDT", "status": "TRADING"}]}
    assert cl._get_trading_symbols() == {"AUSDT"} and len(calls) == 2


def test_get_ohlcv_empty_result_not_refetched_for_30s(monkeypatch):
    now = [5_000.0]
    monkeypatch.setattr(dm_mod.time, "time", lambda: now[0])
    dm = MiddleDataManager()
    calls = []
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: calls.append(tf) or [])
    assert dm.get_ohlcv("AUSDT", "5m", 10) == []
    now[0] += 2
    assert dm.get_ohlcv("AUSDT", "5m", 10) == []                       # 하단 차트 2초 갱신 흉내
    assert calls == ["5m"]
    now[0] += dm_mod._OHLCV_RETRY_SEC
    dm.get_ohlcv("AUSDT", "5m", 10)
    assert calls == ["5m", "5m"]
