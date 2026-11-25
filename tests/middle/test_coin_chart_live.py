"""
tests/middle/test_coin_chart_live.py
2열 Coin Chart 실시간 표시 (2026-11-23 사용자 결정 — 1초 주기·EMA/VWAP 진행 중 봉 포함·Canvas 정식 차트)
 ① 봉 WS: 진행 중 봉(x=false)은 on_live로만 전달 · on_live 없으면 기존처럼 무시 · 마감 봉은 on_closed
    연결 직후 심볼이 바뀌었거나 종료 중이면 닫고 새 심볼로 재연결 (R-5) · 메시지 처리 오류 1번만 기록
 ② get_chart_bars: 마감 봉 캐시 + 차트 WS 마감 봉 + 진행 중 봉 합치기 · 캐시 불변 · 화면 스레드 조회 없음 · 종목 전환 시 초기화
    진행 중 봉은 연결 중·마지막 마감 봉보다 새 봉·기간 끝난 뒤 10초 안일 때만 · 마감 봉이 오면 그 봉의 진행 중 값 버림 (R-2)
 ③ 차트 종목 = 2열이 그리는 화면 선택 종목 — 엔진 1분 갱신 요청(request_selected)으로는 안 바뀜 (F1)
 ④ 4h·1d 차트 전용 251봉 백그라운드 조회 1회 (R-3) · 마감 봉 사이 빈칸 → 다시 받아 채움 (R-5)
 ⑤ CoinChart.prepare: EMA는 전체 봉으로 계산 후 표시 60봉 · VWAP·지지저항은 표시 구간
 ⑥ 차트 그리기: 진행 중 봉 = 마지막 캔들 · 현재가 · 가격 눈금 · 'Fallback Mode' 없음 · 캔버스 재사용
    가격이 모두 같을 때 가운데 · 0.001대 코인 눈금 숫자 구분
 ⑦ 1초 실시간 갱신: 분석 중·Coin Chart 탭일 때만 그림, 그리기 오류가 나도 다시 예약 (R-1)
 ⑧ 데이터 갱신 1회 → 2열 1번만 (상세 갱신 함수의 중복 예약 삭제)
네트워크 없음.
"""
import json
import logging
import threading
import time
import tkinter as tk

import pytest

import core.rate_gate as rate_gate
import middle.data.websocket_klines as wsk
import middle.widget.shared_context as _ctx
from middle.col2_chart_indicators.coin_chart import CoinChart
from middle.data.data_manager import MiddleDataManager
from middle.data.websocket_klines import WebSocketKlines
from middle.models import OHLCVBar
from middle.widget.constants import DIM_TEXT, fmt_price
from middle.widget.middle_panel import MiddlePanel

M = 60_000          # 1분 (ms)
H4 = 14_400_000     # 4시간 (ms)


def _now_floor(span):
    return int(time.time() * 1000) // span * span


def _bar(t, o, h, l, c, span=M):
    return OHLCVBar(t, o, h, l, c, 1.0, 10.0, t + span - 1)


def _msg(sym, tf, t, c, closed):
    return json.dumps({"stream": f"{sym.lower()}@kline_{tf}", "data": {"s": sym, "k": {
        "t": t, "T": t + 59_999, "i": tf, "x": closed, "o": "1", "h": "2", "l": "0.5", "c": str(c),
        "v": "1", "q": "10", "V": "0.5"}}})


def _wait(cond, limit=3.0):
    end = time.time() + limit
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


# ── ① 봉 WS ───────────────────────────────────────────────────
def test_ws_live_bar_only_to_on_live():
    closed, live = [], []
    ws = WebSocketKlines(on_closed=lambda *a: closed.append(a), on_live=lambda *a: live.append(a))
    ws._symbol = "ABCUSDT"
    ws._on_message(None, _msg("ABCUSDT", "1m", 60_000, 1.5, closed=False))
    assert len(live) == 1 and live[0][2].close == 1.5 and closed == [] and ws._last_data_time == 0.0
    ws._on_message(None, _msg("ABCUSDT", "1m", 60_000, 1.7, closed=True))
    assert len(closed) == 1 and closed[0][2].close == 1.7 and ws._last_data_time > 0


def test_ws_without_on_live_ignores_live_bar():
    closed = []
    ws = WebSocketKlines(on_closed=lambda *a: closed.append(a))   # 엔진·상세 갱신용 기존 WS
    ws._symbol = "ABCUSDT"
    ws._on_message(None, _msg("ABCUSDT", "1m", 60_000, 1.5, closed=False))
    assert closed == [] and ws._last_error == ""


def test_ws_callback_error_logged_once(caplog):
    def boom(*a):
        raise RuntimeError("draw store failed")
    ws = WebSocketKlines(on_closed=lambda *a: None, on_live=boom)
    ws._symbol = "ABCUSDT"
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            ws._on_message(None, _msg("ABCUSDT", "1m", 60_000, 1.5, closed=False))
    hits = [r for r in caplog.records if "draw store failed" in r.getMessage()]
    assert len(hits) == 1 and "draw store failed" in ws.last_error   # 같은 오류 반복은 1번만 기록


class _FakeClose:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_ws_on_open_closes_stale_symbol_or_stopped_connection():
    ws = WebSocketKlines(on_closed=lambda *a: None)
    ws._running, ws._symbol, ws._conn_symbol = True, "ETHUSDT", "BTCUSDT"
    app = _FakeClose()
    ws._on_open(app)                                                     # 옛 심볼 연결 → 닫고 즉시 재연결
    assert app.closed and not ws.is_connected and ws._intentional_close
    ws._conn_symbol, ws._intentional_close = "ETHUSDT", False
    app = _FakeClose()
    ws._on_open(app)                                                     # 맞는 심볼 → 유지
    assert not app.closed and ws.is_connected
    ws._running = False
    app = _FakeClose()
    ws._on_open(app)                                                     # 종료 중 → 닫음
    assert app.closed


class _FakeApp:
    """websocket-client WebSocketApp 흉내 — run_forever 시작 시 이전 close()를 잊음(keep_running=True 재설정과 같음)."""
    made: list = []
    hook = None

    def __init__(self, url, on_open, on_message, on_error, on_close):
        self.url, self.on_open, self.ev = url, on_open, threading.Event()
        _FakeApp.made.append(self)
        if _FakeApp.hook:
            _FakeApp.hook()          # 생성 ~ run_forever 사이에 들어온 심볼 교체

    def run_forever(self, **kw):
        self.ev.clear()
        self.on_open(self)
        self.ev.wait(3.0)

    def close(self):
        self.ev.set()


def test_ws_symbol_switch_during_connect_reconnects_new_symbol(monkeypatch):
    monkeypatch.setattr(wsk.websocket, "WebSocketApp", _FakeApp)
    _FakeApp.made = []
    ws = WebSocketKlines(on_closed=lambda *a: None)
    _FakeApp.hook = lambda: (setattr(_FakeApp, "hook", None), ws.set_symbol("ETHUSDT"))
    ws.start("BTCUSDT")
    try:
        assert _wait(lambda: len(_FakeApp.made) >= 2, 1.5)                # 기존: 3초 동안 옛 심볼 연결 유지
        assert "btcusdt@" in _FakeApp.made[0].url and "ethusdt@" in _FakeApp.made[1].url
        assert _wait(lambda: ws.is_connected)
    finally:
        ws.stop()
    assert _wait(lambda: not ws._thread.is_alive())                       # 종료 → 연결 닫힘·스레드 끝


# ── ② get_chart_bars ──────────────────────────────────────────
class _WS:
    def __init__(self):
        self.is_connected = True
        self.calls = []

    def set_symbol(self, s):
        self.calls.append(s)

    def stop(self):
        self.calls.append("stop")


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager()

    def _no_fetch(*a, **k):
        raise AssertionError("차트가 거래소를 새로 조회함")
    monkeypatch.setattr(m._ohlcv_svc, "fetch", _no_fetch)
    m._chart_ws = _WS()
    yield m
    m._running = False


def test_chart_bars_merge_cache_closed_live(dm):
    T = _now_floor(M)
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - (4 - i) * M, 1, 2, 0.5, 1.0 + i) for i in range(3)]}
    dm.set_chart_symbol("ABCUSDT")
    dm._on_chart_closed("ABCUSDT", "1m", _bar(T - M, 4, 5, 3, 4.0))     # 캐시에 아직 없는 마감 봉
    dm._on_chart_live("ABCUSDT", "1m", _bar(T, 4, 6, 3.5, 5.0))         # 진행 중 봉
    dm._on_chart_live("ABCUSDT", "1m", _bar(T, 4, 6.5, 3.5, 6.0))       # 같은 봉 갱신 — 최신 값
    dm._on_chart_live("OTHERUSDT", "1m", _bar(T, 9, 9, 9, 9.0))         # 다른 종목 — 무시
    bars = dm.get_chart_bars("ABCUSDT", "1m")
    assert [b["t"] for b in bars] == [T - 4 * M, T - 3 * M, T - 2 * M, T - M, T]
    assert bars[-1]["c"] == 6.0 and bars[-1]["h"] == 6.5
    assert len(dm._ohlcv_cache["ABCUSDT"]["1m"]) == 3                    # 엔진·지표 캐시 불변


def test_chart_bars_empty_cache_no_fetch_and_switch_clears(dm):
    T = _now_floor(M)
    assert dm.get_chart_bars("NONEUSDT", "5m") == []                    # 조회 없이 빈 목록 (_no_fetch 미호출)
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - M, 1, 2, 0.5, 1.0)]}
    dm.set_chart_symbol("ABCUSDT")
    dm._on_chart_live("ABCUSDT", "1m", _bar(T, 1, 2, 0.5, 1.5))
    dm.set_chart_symbol("XYZUSDT")                                      # 종목 전환 — 이전 실시간 봉 버림
    dm.set_chart_symbol("ABCUSDT")
    assert [b["t"] for b in dm.get_chart_bars("ABCUSDT", "1m")] == [T - M]
    assert dm._chart_ws.calls == ["ABCUSDT", "XYZUSDT", "ABCUSDT"]


def test_closed_bar_replaces_its_live_value(dm):
    """R-2: 봉 마감 직후 그 봉의 진행 중 값(11.0)이 최종값(11.7)을 덮지 않음."""
    T = _now_floor(M)
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - 2 * M, 1, 2, 0.5, 10.0)]}
    dm.set_chart_symbol("ABCUSDT")
    dm._on_chart_live("ABCUSDT", "1m", _bar(T - M, 10, 12, 9, 11.0))
    dm._on_chart_closed("ABCUSDT", "1m", _bar(T - M, 10, 12, 9, 11.7))
    bars = dm.get_chart_bars("ABCUSDT", "1m")
    assert [(b["t"], b["c"]) for b in bars] == [(T - 2 * M, 10.0), (T - M, 11.7)]


def test_live_bar_hidden_when_disconnected_stale_or_older(dm):
    """R-2: 끊김 중·기간 끝난 지 10초 넘은 진행 중 봉·마지막 마감 봉보다 오래된 진행 중 봉은 붙이지 않음."""
    T = _now_floor(M)
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - 3 * M, 1, 2, 0.5, 10.0)]}
    dm.set_chart_symbol("ABCUSDT")
    dm._on_chart_live("ABCUSDT", "1m", _bar(T, 10, 12, 9, 11.0))
    assert dm.get_chart_bars("ABCUSDT", "1m")[-1]["c"] == 11.0          # 연결 중 — 표시
    dm._chart_ws.is_connected = False
    assert dm.get_chart_bars("ABCUSDT", "1m")[-1]["t"] == T - 3 * M     # 끊김 — 마지막 값을 현재가처럼 두지 않음
    dm._chart_ws.is_connected = True
    dm._on_chart_live("ABCUSDT", "1m", _bar(T - 2 * M, 10, 12, 9, 11.0))   # 기간 끝난 지 60초 이상
    assert dm.get_chart_bars("ABCUSDT", "1m")[-1]["t"] == T - 3 * M
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - 3 * M + i * M, 1, 2, 0.5, 11.9) for i in range(3)]}
    dm._on_chart_live("ABCUSDT", "1m", _bar(T - 2 * M, 10, 12, 9, 11.0))   # 캐시 최종 봉보다 오래된 진행 중 값
    bars = dm.get_chart_bars("ABCUSDT", "1m")
    assert [b["c"] for b in bars] == [11.9, 11.9, 11.9]                  # 중간 봉을 덮지 않음


# ── ③ 차트 종목 = 화면 선택 종목 (F1) ────────────────────────────
def test_engine_refresh_request_does_not_move_chart_symbol(dm, monkeypatch):
    monkeypatch.setattr(dm, "_refresh_detail", lambda s: None)
    T = _now_floor(M)
    dm._ohlcv_cache["SELUSDT"] = {"1m": [_bar(T - M, 1, 2, 0.5, 1.0)]}
    dm.set_chart_symbol("SELUSDT")
    dm._on_chart_live("SELUSDT", "1m", _bar(T, 1, 2, 0.5, 1.5))
    dm._engine_sym = "ENGUSDT"
    dm.request_selected("ENGUSDT")                                      # 엔진 1분 갱신 요청 (sel_refresher)
    assert dm._chart_sym == "SELUSDT" and dm._chart_ws.calls == ["SELUSDT"]
    assert dm.get_chart_bars("SELUSDT", "1m")[-1]["c"] == 1.5            # 실시간 봉 유지 (기존: 버려짐)


def test_stop_resets_chart_symbol(dm):
    dm.set_chart_symbol("ABCUSDT")
    ws = dm._chart_ws
    dm.stop_auto_refresh()
    assert ws.calls[-1] == "stop" and dm._chart_sym == "" and dm._chart_bars == {}


# ── ④ 차트 전용 조회 (R-3 4h·1d 251봉 · R-5 빈칸 채움) ─────────────
def _recording_fetch(monkeypatch, dm, make):
    calls = []

    def fetch(sym, tf, limit):
        calls.append((sym, tf, limit, threading.current_thread() is threading.main_thread()))
        return make(tf, limit)
    monkeypatch.setattr(dm._ohlcv_svc, "fetch", fetch)
    monkeypatch.setattr(rate_gate, "remaining", lambda: 0.0)
    return calls


def test_4h_chart_bars_fetched_once_in_background(dm, monkeypatch):
    T4 = _now_floor(H4)
    calls = _recording_fetch(monkeypatch, dm, lambda tf, n: [_bar(T4 - (n - 1 - i) * H4, 1, 2, 0.5, 1.0, H4)
                                                            for i in range(n)])   # 마지막 = 진행 중 봉
    dm._ohlcv_cache["ABCUSDT"] = {"4h": [_bar(T4 - (79 - i) * H4, 1, 2, 0.5, 1.0, H4) for i in range(79)],
                                  "1m": [_bar(_now_floor(M) - M, 1, 2, 0.5, 1.0)]}
    dm._running = True
    dm.set_chart_symbol("ABCUSDT")
    assert len(dm.get_chart_bars("ABCUSDT", "4h")) == 79                # 받기 전 — 캐시 봉으로 (화면 스레드 대기 없음)
    assert _wait(lambda: not dm._chart_fetching)
    bars = dm.get_chart_bars("ABCUSDT", "4h")
    assert len(bars) == 250 and bars[-1]["t"] == T4 - H4                # 마감 250봉 (진행 중 봉은 차트 WS 몫)
    dm.get_chart_bars("ABCUSDT", "4h")
    dm.get_chart_bars("ABCUSDT", "1m")                                  # 1m~1h는 캐시 200봉 — 추가 조회 없음
    assert calls == [("ABCUSDT", "4h", 251, False)]                       # 1회·백그라운드
    assert len(dm._ohlcv_cache["ABCUSDT"]["4h"]) == 79                    # 엔진·1열 캐시 불변


def test_chart_fetch_failure_or_block_waits_before_retry(dm, monkeypatch):
    T4 = _now_floor(H4)
    calls = _recording_fetch(monkeypatch, dm, lambda tf, n: [])
    dm._ohlcv_cache["ABCUSDT"] = {"1d": [_bar(T4 - H4, 1, 2, 0.5, 1.0, H4)]}
    dm._running = True
    dm.set_chart_symbol("ABCUSDT")
    dm.get_chart_bars("ABCUSDT", "1d")
    assert _wait(lambda: not dm._chart_fetching)
    for _ in range(3):
        assert len(dm.get_chart_bars("ABCUSDT", "1d")) == 1              # 실패 — 캐시 봉으로 계속 그림
    assert calls == [("ABCUSDT", "1d", 251, False)]                       # 30초 안 재조회 없음
    monkeypatch.setattr(rate_gate, "remaining", lambda: 30.0)           # 차단 중
    dm.set_chart_symbol("XYZUSDT")
    dm._ohlcv_cache["XYZUSDT"] = {"1d": [_bar(T4 - H4, 1, 2, 0.5, 1.0, H4)]}
    dm.get_chart_bars("XYZUSDT", "1d")
    assert _wait(lambda: not dm._chart_fetching)
    assert len(calls) == 1 and "1d" in dm._chart_fail                    # 차단 중 조회하지 않음


def test_gap_in_closed_bars_refetched(dm, monkeypatch):
    """R-5: 캐시 마지막 봉과 WS 마감 봉 사이가 비면(재연결 중 마감) 차트용으로 다시 받아 채움."""
    T = _now_floor(M)
    calls = _recording_fetch(monkeypatch, dm, lambda tf, n: [_bar(T - (5 - i) * M, 1, 2, 0.5, 1.0) for i in range(6)])
    dm._ohlcv_cache["ABCUSDT"] = {"1m": [_bar(T - (5 - i) * M, 1, 2, 0.5, 1.0) for i in range(3)]}   # T-5M..T-3M
    dm._running = True
    dm.set_chart_symbol("ABCUSDT")
    dm._on_chart_closed("ABCUSDT", "1m", _bar(T - M, 1, 2, 0.5, 1.0))   # T-2M 빠짐
    assert _wait(lambda: not dm._chart_fetching)
    assert calls == [("ABCUSDT", "1m", 200, False)]
    assert [b["t"] for b in dm.get_chart_bars("ABCUSDT", "1m")] == [T - k * M for k in (5, 4, 3, 2, 1)]
    dm._on_chart_closed("ABCUSDT", "1m", _bar(T, 1, 2, 0.5, 1.0))       # 이어지는 봉 — 조회 없음
    assert len(calls) == 1


# ── ⑤ CoinChart.prepare ───────────────────────────────────────
def test_prepare_ema_full_series_shown_60():
    closes = [100 + (i % 17) * 1.5 + i * 0.3 for i in range(200)]
    candles = [{"o": c - 1, "h": c + 1, "l": c - 2, "c": c, "v": 5.0} for c in closes]
    d = CoinChart.prepare(candles, "ABCUSDT")
    assert len(d.candles) == 60 and len(d.ema50_line) == 60 and len(d.vwap_line) == 60
    assert d.ema50_line == CoinChart._ema(closes, 50)[-60:]             # 전체 봉 EMA의 표시 구간
    assert d.ema50_line != CoinChart._ema(closes[-60:], 50)              # 기존(60봉만) 계산과 다름
    assert d.vwap_line == CoinChart._vwap(candles[-60:])
    assert d.support_level == min(c["l"] for c in candles[-20:])


# ── ⑥ 차트 그리기 ─────────────────────────────────────────────
@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.geometry("600x400+20+20")
    yield r
    r.destroy()


class _ChartDM:
    def __init__(self, bars):
        self.bars = bars
        self.chart_syms = []

    def get_chart_bars(self, sym, interval):
        return self.bars

    def set_chart_symbol(self, sym):
        self.chart_syms.append(sym)


def _chart_panel(root, monkeypatch, bars):
    monkeypatch.setattr(_ctx, "_data_mgr", _ChartDM(bars))
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p.pack(fill="both", expand=True)
    p._chart_f = tk.Frame(p, width=500, height=300)
    p._chart_f.pack(fill="both", expand=True)
    p._sel_var, p._tf_var = tk.StringVar(root, "ABCUSDT"), tk.StringVar(root, "1분봉")
    root.update()
    return p


def _texts(p):
    cv = p._chart_f.winfo_children()[0]
    return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]


def _axis_labels(p):
    """오른쪽 가격 눈금 5개 (회색) — 현재가 상자 글자(검정) 제외."""
    cv = p._chart_f.winfo_children()[0]
    return [cv.itemcget(i, "text") for i in cv.find_all()
            if cv.type(i) == "text" and cv.itemcget(i, "anchor") == "w" and cv.itemcget(i, "fill") == DIM_TEXT]


def test_draw_chart_live_last_candle_price_axis_no_fallback(root, monkeypatch):
    bars = [{"t": i * 60_000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1.0} for i in range(199)]
    bars.append({"t": 199 * 60_000, "o": 100.5, "h": 104.0, "l": 100.0, "c": 103.25, "v": 1.0})   # 진행 중 봉
    p = _chart_panel(root, monkeypatch, bars)
    p._refresh_chart()
    t = _texts(p)
    assert "ABCUSDT  1분봉" in t and not any("Fallback" in x for x in t)
    assert fmt_price(103.25) in t                                        # 현재가 = 진행 중 봉 종가 (일반 가격 표시 그대로)
    assert fmt_price(104.0) in t and fmt_price(99.0) in t                # 가격 눈금 위·아래 끝
    assert _ctx._data_mgr.chart_syms[-1] == "ABCUSDT"                    # 차트 WS = 그리는 종목 (F1)
    cv1 = p._chart_f.winfo_children()[0]
    bars[-1] = dict(bars[-1], c=103.75)                                  # 진행 중 봉 갱신
    p._refresh_chart()
    assert p._chart_f.winfo_children() == [cv1]                          # 캔버스 재사용 (새 위젯 아님)
    assert fmt_price(103.75) in _texts(p) and fmt_price(103.25) not in _texts(p)


def test_draw_chart_empty_shows_loading(root, monkeypatch):
    p = _chart_panel(root, monkeypatch, [])
    p._refresh_chart()
    assert _texts(p) == ["ABCUSDT\n데이터 로드 중..."]


def test_draw_chart_flat_prices_centered(root, monkeypatch):
    """가격이 모두 같으면 가짜 0~1 눈금 대신 가격 주변 눈금 · 현재가 선이 가운데 (기존: 바닥)."""
    p = _chart_panel(root, monkeypatch, [{"t": 0, "o": 0.5, "h": 0.5, "l": 0.5, "c": 0.5, "v": 0.0}])
    p._refresh_chart()
    labels = _axis_labels(p)
    assert len(labels) == 5 and len(set(labels)) == 5
    assert all(0.4997 <= float(x) <= 0.5003 for x in labels)
    cv = p._chart_f.winfo_children()[0]
    cur = [i for i in cv.find_all() if cv.type(i) == "text" and cv.itemcget(i, "fill") == "#000000"]
    H = p._chart_f.winfo_height()
    assert abs(cv.coords(cur[0])[1] - (24 + (H - 18)) / 2) <= 1             # 그림 영역 가운데


def test_draw_chart_tiny_price_axis_distinct(root, monkeypatch):
    """0.001대 코인 — 눈금 숫자 반복(0.00118 ×4) 없이 구분 · 현재가는 눈금보다 1자리 더 · 캔버스 안."""
    bars = [{"t": i, "o": 0.001185, "h": 0.001190, "l": 0.001180, "c": 0.001185, "v": 1.0} for i in range(59)]
    bars.append({"t": 59, "o": 0.001185, "h": 0.001187, "l": 0.001184, "c": 0.0011864, "v": 1.0})
    p = _chart_panel(root, monkeypatch, bars)
    p._refresh_chart()
    labels = _axis_labels(p)
    assert len(set(labels)) == 5 and labels[0] == "0.001180" and labels[-1] == "0.001190"
    assert "0.0011864" in _texts(p)
    cv = p._chart_f.winfo_children()[0]
    W = p._chart_f.winfo_width()
    assert all(cv.bbox(i)[2] <= W for i in cv.find_all() if cv.type(i) == "text")


# ── ⑦ 1초 실시간 갱신 ────────────────────────────────────────
def test_live_tick_draws_only_in_analysis_chart_tab(root, monkeypatch):
    p = _chart_panel(root, monkeypatch, [])
    drawn, scheduled = [], []
    p._refresh_chart = lambda: drawn.append(1)
    p.after = lambda ms, fn: scheduled.append(ms)
    for state, tab, expect in (("ANALYSIS", "chart", 1), ("ANALYSIS", "mtf", 0), ("RANKING", "chart", 0)):
        drawn.clear()
        p._app_state, p._cur_chart_tab = state, tab
        p._chart_live_tick()
        assert len(drawn) == expect, (state, tab)
    assert scheduled == [1000, 1000, 1000]                               # 항상 1초 뒤 다시 예약


def test_live_tick_reschedules_after_draw_error(root, monkeypatch, caplog):
    """R-1: 그리기 오류가 나도 1초 갱신이 멈추지 않음 (기존: TclError 외 예외면 다시 예약 안 됨)."""
    p = _chart_panel(root, monkeypatch, [])
    scheduled = []
    p._app_state, p._cur_chart_tab = "ANALYSIS", "chart"

    def boom():
        raise ValueError("bad bar")
    p._refresh_chart = boom
    p.after = lambda ms, fn: scheduled.append(ms)
    with caplog.at_level(logging.ERROR):
        p._chart_live_tick()
    assert scheduled == [1000] and any("1초 갱신 오류" in r.getMessage() for r in caplog.records)


# ── ⑧ 데이터 갱신 1회 → 2열 1번 ───────────────────────────────
def test_detail_refresh_does_not_schedule_col2(root):
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._app_state, p._cur_chart_tab = "ANALYSIS", "chart"
    for name in ("_refresh_header", "_refresh_indicators", "_refresh_ema", "_refresh_deriv",
                 "_refresh_energy", "_refresh_verdict", "_refresh_tf_buttons"):
        setattr(p, name, lambda: None)
    scheduled = []
    p.after = lambda ms, fn=None: scheduled.append(ms)
    p._do_refresh_detail()
    assert scheduled == []                                               # 2열은 _on_data_ready 쪽 1번만
