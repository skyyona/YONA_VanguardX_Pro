"""
middle/data/websocket_ticker.py
Binance USDT-M Futures 실시간 Ticker WebSocket 클라이언트

스트림: wss://fstream.binance.com/stream?streams=!miniTicker@arr
주기:   1초마다 서버 자동 Push
비용:   Rate Limit 0 weight (완전 무료)

메시지 형식:
  {"stream":"!miniTicker@arr","data":[
    {"e":"24hrMiniTicker","s":"BTCUSDT",
     "c":"64000","o":"63500","h":"65000","l":"62000","v":"1234","q":"79012345"},
    ...
  ]}
  c=현재가, o=24h시가, h=고가, l=저가, v=거래량(base), q=거래대금(USDT)
  24h 변동률 = (c - o) / o × 100  (클라이언트에서 계산)
"""
from __future__ import annotations

import json
import threading
import time

import websocket   # websocket-client

from middle.models import SymbolTicker

_STREAM_URL      = "wss://fstream.binance.com/stream?streams=!miniTicker@arr"
_RECONNECT_DELAY = 5   # 재연결 대기 (초)


class WebSocketTicker:
    """Binance Futures 전체 심볼 실시간 ticker WebSocket 클라이언트.

    매 1초마다 Push 수신 → on_update 콜백 호출.
    자동 재연결 지원.
    """

    def __init__(self, on_update: "callable") -> None:
        """
        on_update: list[SymbolTicker] → None  (DataManager._on_ws_ticker_update)
        """
        self._on_update   = on_update
        self._ws: websocket.WebSocketApp | None = None
        self._running       = False
        self._connected     = False
        self._data_received = False   # 실제 데이터 수신 여부 (연결 성공과 별개)
        self._thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def has_received_data(self) -> bool:
        """실제 데이터를 받은 적 있는지 (연결만 됐는지 vs 데이터도 왔는지 구분)."""
        return self._data_received

    # ── 공개 인터페이스 ───────────────────────────────────────
    def start(self) -> None:
        """백그라운드 스레드에서 WebSocket 연결 시작."""
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """WebSocket 연결 종료."""
        self._running   = False
        self._connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # ── 내부 루프 ─────────────────────────────────────────────
    def _loop(self) -> None:
        """재연결 자동화 루프."""
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    _STREAM_URL,
                    on_open    = self._on_open,
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            finally:
                self._connected = False
            if self._running:
                time.sleep(_RECONNECT_DELAY)   # 재연결 대기

    # ── WebSocket 이벤트 핸들러 ───────────────────────────────
    def _on_open(self, ws) -> None:
        self._connected = True

    def _on_close(self, ws, code, msg) -> None:
        self._connected = False

    def _on_error(self, ws, error) -> None:
        self._connected = False

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
            items   = payload.get("data", [])
            if not isinstance(items, list):
                return
            tickers = self._parse(items)
            if tickers:
                self._data_received = True   # 실제 데이터 수신 확인
                self._on_update(tickers)
        except Exception:
            pass

    # ── 파싱 ─────────────────────────────────────────────────
    def _parse(self, items: list) -> list[SymbolTicker]:
        """miniTicker 메시지 배열 → list[SymbolTicker]."""
        result: list[SymbolTicker] = []
        for item in items:
            sym = item.get("s", "")
            if not sym.endswith("USDT"):
                continue
            try:
                close  = float(item.get("c", 0))
                open_p = float(item.get("o", 0))
                pct    = (close - open_p) / open_p * 100.0 if open_p > 0 else 0.0
                result.append(SymbolTicker(
                    symbol           = sym,
                    last_price       = close,
                    price_change     = close - open_p,
                    price_change_pct = round(pct, 4),
                    volume_usdt      = float(item.get("q", 0)),
                    high_24h         = float(item.get("h", 0)),
                    low_24h          = float(item.get("l", 0)),
                ))
            except (ValueError, TypeError):
                continue
        return result
