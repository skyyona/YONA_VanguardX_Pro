"""
tests/middle/test_websocket_klines.py
WebSocketKlines 단위 테스트 — 네트워크 없이 검증.
"""
import json
import sys
import types
import time

# websocket-client 가 테스트 환경에 없어도 import 가능하도록 stub 삽입
_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from middle.data.websocket_klines import WebSocketKlines


def _make_kline_msg(symbol: str, tf: str, closed: bool) -> str:
    """_on_message 에 직접 주입할 kline 메시지 문자열 생성."""
    return json.dumps({
        "stream": f"{symbol.lower()}@kline_{tf}",
        "data": {
            "e": "kline",
            "s": symbol,
            "k": {"t": 1_700_000_000_000, "T": 1_700_000_059_999, "i": tf, "x": closed,
                  "o": "63900", "h": "64100", "l": "63800", "c": "64000", "v": "12.5", "q": "800000"},
        },
    })


# ── T-1 ──────────────────────────────────────────────────────────────────────

def test_on_message_ignores_unclosed_candle():
    """x=False(미마감) 메시지에서 콜백을 호출하지 않는다."""
    called = []
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: called.append((sym, tf, bar)))
    ws._symbol = "BTCUSDT"
    ws._on_message(None, _make_kline_msg("BTCUSDT", "1m", closed=False))
    assert called == []


# ── T-2 ──────────────────────────────────────────────────────────────────────

def test_on_message_ignores_symbol_mismatch():
    """심볼 불일치 메시지를 무시한다."""
    called = []
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: called.append((sym, tf, bar)))
    ws._symbol = "BTCUSDT"
    ws._on_message(None, _make_kline_msg("ETHUSDT", "1m", closed=True))
    assert called == []


# ── T-3 ──────────────────────────────────────────────────────────────────────

def test_on_message_calls_callback_on_closed_candle():
    """x=True + 심볼 일치에서 마감 봉 최종값(OHLCVBar)과 함께 콜백을 호출하고 has_received_data 가 True 가 된다."""
    called = []
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: called.append((sym, tf, bar)))
    ws._symbol = "BTCUSDT"
    ws._on_message(None, _make_kline_msg("BTCUSDT", "1m", closed=True))
    assert [(c[0], c[1]) for c in called] == [("BTCUSDT", "1m")]
    bar = called[0][2]
    assert (bar.open_time, bar.close_time) == (1_700_000_000_000, 1_700_000_059_999)
    assert (bar.open, bar.high, bar.low, bar.close) == (63900.0, 64100.0, 63800.0, 64000.0)
    assert (bar.volume, bar.quote_volume) == (12.5, 800000.0)
    assert ws.has_received_data is True


# ── T-4 ──────────────────────────────────────────────────────────────────────

def test_set_symbol_sets_intentional_close():
    """set_symbol() 호출 시 _intentional_close 가 True 로 설정된다."""
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: None)
    ws._symbol = "BTCUSDT"
    ws._intentional_close = False
    ws.set_symbol("ETHUSDT")
    assert ws._intentional_close is True
    assert ws._symbol == "ETHUSDT"


# ── T-5 ──────────────────────────────────────────────────────────────────────

def test_on_error_sets_last_error_and_disconnected():
    """_on_error 후 last_error 가 외부에서 읽히고 is_connected 가 False 다."""
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: None)
    ws._symbol     = "BTCUSDT"
    ws._connected  = True
    ws._on_error(None, RuntimeError("test error"))
    assert ws.is_connected is False
    assert "BTCUSDT" in ws.last_error
    assert "test error" in ws.last_error


# ── T-6 ──────────────────────────────────────────────────────────────────────

def test_start_sets_running_and_creates_thread():
    """start() 호출 후 _running=True 이고 스레드가 생성된다 (네트워크 없이 검증)."""
    ws = WebSocketKlines(on_closed=lambda sym, tf, bar: None)
    assert ws._running is False
    assert ws._thread is None
    ws.start("")   # 빈 심볼 — _loop 내 time.sleep(1) 대기만 수행
    try:
        assert ws._running is True
        assert ws._thread is not None
        assert ws._thread.is_alive()
    finally:
        ws.stop()
