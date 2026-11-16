"""
tests/middle/test_stage3_bar_close.py
STAGE3 봉 마감 맞춤·새 봉만 받기·이번 분 사용량 상한 (2026-11-16) — 네트워크 없이 대역.
 ① 매분 마감된 TF만 조회 (나머지 TF는 저장 봉 재사용)
 ② 저장 봉이 있으면 새 봉만(limit 3) 받아 이어붙임 → 전체 조회와 같은 봉·같은 지표. 빠진 봉 → 전체 조회
    새 봉 미게시(마감 직후) → 저장 봉 유지 + 같은 분 재시도 표시, 재시도에서 최신 종목은 조회·계산 생략
 ③ 이번 달력 분 IP 사용량 1,900 이상 → STAGE2·STAGE3·예고 종목 조회를 다음 분까지 미룸
가짜 시장: 봉 값이 봉 번호로만 정해짐(마감 봉 불변) · 마감 후 pub_ms 지나야 조회됨 · 응답 마지막(진행 중) 봉은 파싱에서 제외.
"""
import inspect
import math
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

import core.rate_gate as rg
from middle.data import data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager, _STAGE3_FIELDS
from middle.models import OHLCVBar, SymbolTicker

_TF_MS = dm_mod._TF_MS
_LIMITS = dm_mod._KLINES_LIMITS
_T0 = 1_763_251_200_000          # 2025-11-16 00:00:00 UTC — 1d·4h·1h·15m·5m·3m·1m 모두 마감 경계 (epoch 배수)
assert all(_T0 % ms == 0 for ms in _TF_MS.values())


def _bar(sym: str, tf: str, i: int) -> OHLCVBar:
    step, s = _TF_MS[tf], len(sym)
    c = 100.0 + 0.01 * i + 3.0 * math.sin(i / 6.0 + s) + 1.2 * math.sin(i / 2.3)
    o = c - 0.3 * math.cos(i / 3.0)
    v = 1000.0 + 37.0 * (i % 11)
    return OHLCVBar(i * step, o, max(o, c) + 0.4, min(o, c) - 0.4, c, v, v * c, i * step + step - 1)


class _Market:
    """klines 대역 — now 기준 게시된 마지막 마감 봉까지 limit-1개 반환 (실제: limit개 중 진행 중 1개를 파싱에서 제외)."""
    def __init__(self, now, pub_ms=7_000):
        self.now, self.pub_ms, self.calls = now, pub_ms, []

    def fetch(self, symbol, tf, limit=None):
        self.calls.append((symbol, tf, limit))
        step = _TF_MS[tf]
        last = (self.now[0] - self.pub_ms) // step - 1       # 게시된 마지막 마감 봉 번호
        return [_bar(symbol, tf, i) for i in range(last - (limit - 1) + 1, last + 1)]


def _dm(now, syms=("BTCUSDT",), pub_ms=7_000):
    dm = MiddleDataManager()
    mk = _Market(now, pub_ms)
    dm._ohlcv_svc = mk
    dm._sorted_tickers = [SymbolTicker(s, 130.0, 1.0, 1.0, 1e9, 131.0, 99.0) for s in syms]
    return dm, mk


def _clock(monkeypatch, start):
    now = [start]
    monkeypatch.setattr(dm_mod.time, "time", lambda: now[0] / 1000.0)
    return now


def _full_expect(sym, tf, now_ms, pub_ms=7_000):
    return _Market([now_ms], pub_ms).fetch(sym, tf, _LIMITS[tf])


def _ind_view(ind):
    """STAGE3 담당 필드 — 시간 경과 문구(elapsed)는 실행 시각마다 달라 제외."""
    out = {}
    for k in _STAGE3_FIELDS:
        v = ind.get(k)
        if isinstance(v, dict):
            v = {a: b for a, b in v.items() if a != "elapsed"}
        out[k] = v
    return out


def test_only_closed_tfs_fetched_each_minute_with_incremental_limit(monkeypatch):
    now = _clock(monkeypatch, _T0 + 8_000)
    dm, mk = _dm(now)
    dm._refresh_topn_klines(1)
    assert sorted(mk.calls) == sorted(("BTCUSDT", tf, _LIMITS[tf]) for tf in _LIMITS)   # 처음: 7TF 전체 조회

    def run_at(offset_ms):
        mk.calls.clear()
        now[0] = _T0 + offset_ms
        dm._refresh_topn_klines(1)
        return {tf: lim for _, tf, lim in mk.calls}

    # 매분 실행 — 마감된 TF만 새 봉 3개 요청
    assert run_at(60_000 + 8_000) == {"1m": 3}                                  # 00:01 — 1m만
    assert run_at(120_000 + 8_000) == {"1m": 3}                                 # 00:02 — 1m만
    assert run_at(180_000 + 8_000) == {"1m": 3, "3m": 3}                        # 00:03 — 1m·3m
    assert run_at(300_000 + 8_000) == {"1m": 3, "5m": 3}                        # 00:05 — 00:04 건너뜀: 1m 새 봉 2개 = 응답 2개 → 이어붙임
    # 실행 건너뜀으로 새 봉이 응답(마감 2개)보다 많으면 빠진 봉 → 전체 조회 (dict는 마지막 요청 = 전체 조회 limit)
    assert run_at(900_000 + 8_000) == {"1m": 200, "3m": 200, "5m": 3, "15m": 3}            # 00:15 — 1m 10·3m 4 부족
    assert run_at(3_600_000 + 8_000) == {"1m": 200, "3m": 200, "5m": 200, "15m": 200, "1h": 3}   # 01:00
    assert run_at(14_400_000 + 8_000) == {"1m": 200, "3m": 200, "5m": 200, "15m": 200, "1h": 200, "4h": 3}   # 04:00
    assert run_at(86_400_000 + 8_000) == {**{tf: _LIMITS[tf] for tf in _LIMITS}, "1d": 3}   # 다음 날 00:00 — 1d 1봉 이어붙임


def test_incremental_bars_and_indicators_equal_full_fetch(monkeypatch):
    """매분 이어붙인 봉·지표 == 같은 시각 전체 조회 봉·지표 (마감 봉 불변) — 3시간 15분 연속, 4h·1d 마감 포함."""
    now = _clock(monkeypatch, _T0 - 7_200_000 + 8_000)          # 전날 22:00 시작 → 00:00 1d·4h 마감 지남
    dm, mk = _dm(now, syms=("BTCUSDT", "ETHUSDT"))
    dm._refresh_topn_klines(2)
    limits_seen = set()
    for m in range(1, 196):
        now[0] = _T0 - 7_200_000 + m * 60_000 + 8_000
        mk.calls.clear()
        dm._refresh_topn_klines(2)
        limits_seen |= {lim for _, _, lim in mk.calls}
        ref, _ = _dm([now[0]], syms=("BTCUSDT", "ETHUSDT"))
        ref._refresh_topn_klines(2)                               # 비교 기준: 매번 7TF 전체 조회
        for sym in ("BTCUSDT", "ETHUSDT"):
            assert dm._ohlcv_cache[sym] == ref._ohlcv_cache[sym]
            assert _ind_view(dm._ind_cache[sym]) == _ind_view(ref._ind_cache[sym])
    assert limits_seen == {3}                                     # 매분 실행이면 전체 조회 없음
    assert {tf: len(b) for tf, b in dm._ohlcv_cache["BTCUSDT"].items()} == {tf: n - 1 for tf, n in _LIMITS.items()}


def test_gap_triggers_full_refetch_and_result_equals_full(monkeypatch):
    now = _clock(monkeypatch, _T0 + 8_000)
    dm, mk = _dm(now)
    dm._refresh_topn_klines(1)
    now[0] = _T0 + 4 * 60_000 + 8_000                             # 3분 건너뜀 → 1m 새 마감 봉 4개 > 응답 2개
    mk.calls.clear()
    dm._refresh_topn_klines(1)
    assert ("BTCUSDT", "1m", 3) in mk.calls and ("BTCUSDT", "1m", 200) in mk.calls
    assert dm._ohlcv_cache["BTCUSDT"]["1m"] == _full_expect("BTCUSDT", "1m", now[0])
    assert dm._ohlcv_cache["BTCUSDT"]["3m"] == _full_expect("BTCUSDT", "3m", now[0])   # 3m 1봉 → 이어붙임


def test_late_publication_keeps_bars_and_retries_same_minute(monkeypatch):
    now = _clock(monkeypatch, _T0 + 60_000 + 30_000)
    dm, mk = _dm(now, syms=("BTCUSDT", "ETHUSDT"), pub_ms=12_000)  # 마감 후 12초 지나야 조회됨
    dm._refresh_topn_klines(2)
    assert dm._stage3_stale is False
    now[0] = _T0 + 120_000 + 8_000                                # 00:02:08 — 00:01 1m 봉 아직 미게시
    before = dict(dm._ohlcv_cache["BTCUSDT"])
    dm._refresh_topn_klines(2)
    assert dm._stage3_stale is True                               # 같은 분 재시도 표시
    assert dm._ohlcv_cache["BTCUSDT"] == before                   # 저장 봉 유지 (빈 갱신·되돌림 없음)
    now[0] = _T0 + 120_000 + 13_000                               # 5초 뒤 재시도 — 게시됨
    mk.calls.clear()
    dm._refresh_topn_klines(2)
    assert dm._stage3_stale is False
    assert sorted(mk.calls) == [("BTCUSDT", "1m", 3), ("ETHUSDT", "1m", 3)]
    assert dm._ohlcv_cache["BTCUSDT"]["1m"] == _full_expect("BTCUSDT", "1m", now[0], 12_000)
    mk.calls.clear()
    dm._ind_cache["BTCUSDT"]["_mark"] = 1                         # 다시 실행: 최신 → 조회·계산 생략 (캐시 그대로)
    dm._refresh_topn_klines(2)
    assert mk.calls == [] and dm._ind_cache["BTCUSDT"].get("_mark") == 1


def test_loop_triggers_on_minute_close_plus_delay_and_stop_resets():
    src = inspect.getsource(MiddleDataManager._auto_refresh_loop)
    assert "(_now_ms - _STAGE3_DELAY_MS) // 60_000" in src
    assert "self._stage3_stale and _now_ms % 60_000 < _STAGE3_RETRY_UNTIL" in src
    assert "_elapsed % _STAGE3_INTERVAL == 0:\n                self._start_job(\"stage3\"" not in src   # 60초 주기 실행 제거
    m = lambda ms: (ms - dm_mod._STAGE3_DELAY_MS) // 60_000
    assert m(_T0 + 7_999) == m(_T0 - 1) == _T0 // 60_000 - 1 and m(_T0 + 8_000) == _T0 // 60_000
    assert m(_T0 + 8_000) != m(_T0 + 7_999)                       # 분 0초 + 8초에 다음 실행
    dm = MiddleDataManager()
    dm._stage3_minute, dm._stage3_stale = 123, True
    dm.stop_auto_refresh()
    assert (dm._stage3_minute, dm._stage3_stale) == (-1, False)


def test_soft_cap_waits_until_next_minute(monkeypatch):
    gate = types.SimpleNamespace(last_weight=None)
    monkeypatch.setattr(rg, "_gate", gate)
    slept = []
    t = 60 * 16_667 + 20.5                                        # 분 안 20.5초 (1,000,040.5)
    f = lambda: rg.defer_if_over_soft_cap(sleep=slept.append, clock=lambda: t)
    assert f() == 0.0                                             # 기록 없음
    gate.last_weight = (1_899, t - 1)
    assert f() == 0.0                                             # 상한 미만
    gate.last_weight = (2_100, t - 21)                            # 지난 분 기록 → 이미 초기화됨
    assert f() == 0.0
    gate.last_weight = (1_900, t - 3)
    assert f() == 60.0 - 20.5 + 1.0 and slept == [40.5]           # 다음 분 1초까지
    monkeypatch.setattr(rg, "_gate", None)
    assert rg.defer_if_over_soft_cap(sleep=slept.append) == 0.0   # 장치 설치 전


def test_stage_and_forecast_requests_deferred_before_fetch(monkeypatch):
    order = []
    monkeypatch.setattr(rg, "defer_if_over_soft_cap", lambda: order.append("defer") or 0.0)
    dm = MiddleDataManager()
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: order.append("k") or [])
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: order.append("ls"))
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.0, 0.0))
    dm._client = types.SimpleNamespace(fetch_all_premium_index=lambda: [], fetch_funding_info=lambda: [])
    dm._sorted_tickers = [SymbolTicker("AUSDT", 100.0, 1.0, 1.0, 1e6, 101.0, 99.0)]
    dm._refresh_topn_klines(1)
    assert order[0] == "defer" and order.count("defer") == 1 and "k" in order
    order.clear()
    dm._refresh_topn_scores(1)
    assert order[:2] == ["defer", "ls"]
    order.clear()
    dm._forecast_one = lambda s, f: order.append("fc")
    dm._forecast_one_safe("AUSDT", True)
    assert order == ["defer", "fc"]
