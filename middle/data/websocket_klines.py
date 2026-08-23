"""
middle/data/websocket_klines.py
선택 심볼 kline WebSocket 클라이언트

스트림: wss://fstream.binance.com/stream?streams={sym}@kline_1m/.../@kline_1h
주기:   봉 마감(x=True) 시 콜백 호출
비용:   Rate Limit 0 weight (완전 무료)

메시지 형식:
  {"stream":"btcusdt@kline_1m","data":{"e":"kline","s":"BTCUSDT",
   "k":{"i":"1m","x":true,"c":"64000",...}}}
  x=True 가 봉 마감 신호
"""
from __future__ import annotations

import json
import threading
import time

import websocket   # websocket-client

_RECONNECT_DELAY = 5   # 재연결 대기 (초)
_TFS = ("1m", "3m", "5m", "15m", "1h")   # 모니터링 TF (거시 포함)


class WebSocketKlines:
    """선택 심볼 kline 스트림 WebSocket 클라이언트.

    봉 마감(x=True) 감지 시 on_closed(symbol, tf) 콜백 호출.
    set_symbol()로 심볼 교체 가능.
    """

    def __init__(self, on_closed: "callable") -> None:
        """
        on_closed: (symbol: str, tf: str) -> None
        """
        self._on_closed = on_closed
        self._ws: websocket.WebSocketApp | None = None
        self._running = False
        self._symbol  = ""
        self._intentional_close = False
        self._last_error: str = ""
        self._thread: threading.Thread | None = None

    # ── 공개 인터페이스 ───────────────────────────────────────

    def start(self, symbol: str) -> None:
        """백그라운드 스레드에서 WebSocket 연결 시작."""
        self._symbol  = symbol
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def set_symbol(self, symbol: str) -> None:
        """심볼 교체 — 기존 연결 종료 후 새 심볼로 자동 재연결."""
        if symbol == self._symbol:
            return
        self._symbol = symbol
        self._intentional_close = True
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def stop(self) -> None:
        """WebSocket 연결 종료."""
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    # ── 내부 루프 ─────────────────────────────────────────────

    def _build_url(self) -> str:
        sym     = self._symbol.lower()
        streams = "/".join(f"{sym}@kline_{tf}" for tf in _TFS)
        return f"wss://fstream.binance.com/stream?streams={streams}"

    def _loop(self) -> None:
        """재연결 자동화 루프."""
        while self._running:
            if not self._symbol:
                time.sleep(1)
                continue
            try:
                self._ws = websocket.WebSocketApp(
                    self._build_url(),
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            if self._running and not self._intentional_close:
                time.sleep(_RECONNECT_DELAY)
            self._intentional_close = False

    # ── WebSocket 이벤트 핸들러 ───────────────────────────────

    def _on_close(self, ws, code, msg) -> None:
        pass

    def _on_error(self, ws, error) -> None:
        self._last_error = f"[klines:{self._symbol}] {error}"

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
            data    = payload.get("data", {})
            kline   = data.get("k", {})
            if not kline.get("x", False):   # 봉 마감 아니면 무시
                return
            sym = data.get("s", "")
            tf  = kline.get("i", "")
            if sym and tf and sym == self._symbol:
                self._on_closed(sym, tf)
        except Exception:
            pass
