"""
middle/data/websocket_klines.py
선택 심볼 kline WebSocket 클라이언트

스트림: wss://fstream.binance.com/market/stream?streams={sym}@kline_1m/.../@kline_1d
        (구 /stream 경로는 Binance가 2026-04-23 폐지 — 연결은 되나 데이터 없음, 2026-10-26 실측)
주기:   봉 마감(x=True) 시 콜백 호출 — 마감 봉 최종 OHLCV 함께 전달
        on_live 지정 시 진행 중 봉(x=False, 약 0.33초마다 — 2026-11-23 실측)도 전달 (2열 Coin Chart 실시간 표시 전용)
        (2026-10-26 실측: 마감 후 0.01~3초 도착, 64/64 REST 최종값과 일치.
         REST klines는 마감 봉 최종값을 마감 후 4.75~7.5초부터 안정 제공)
비용:   Rate Limit 0 weight (완전 무료)

메시지 형식:
  {"stream":"btcusdt@kline_1m","data":{"e":"kline","s":"BTCUSDT",
   "k":{"t":..,"T":..,"i":"1m","x":true,"o":..,"h":..,"l":..,"c":"64000","v":..,"q":..}}}
  x=True 가 봉 마감 신호, t/T = 봉 시작/마감 시각(ms)
"""
from __future__ import annotations

import json
import logging
import threading
import time

import websocket   # websocket-client

from middle.models import OHLCVBar

_RECONNECT_DELAY = 5   # 재연결 대기 (초)
_STALE_SEC       = 90  # 마지막 마감 봉 수신 후 이 시간이 지나면 "수신 중 아님" — 1m 봉 마감 60초 + 여유 (2026-11-12)
_TFS = ("1m", "3m", "5m", "15m", "1h", "4h", "1d")   # 봉 마감 감지 TF — data_manager _DETAIL_TFS 전체


class WebSocketKlines:
    """선택 심볼 kline 스트림 WebSocket 클라이언트.

    봉 마감(x=True) 감지 시 on_closed(symbol, tf, bar) 콜백 호출 (bar = 마감 봉 최종 OHLCVBar).
    on_live 지정 시 진행 중 봉(x=False)은 on_live(symbol, tf, bar)로 전달 (2열 Coin Chart 전용 WS).
    set_symbol()로 심볼 교체 가능.
    """

    def __init__(self, on_closed: "callable", on_live: "callable | None" = None) -> None:
        """
        on_closed: (symbol: str, tf: str, bar: OHLCVBar) -> None — 봉 마감(x=True)
        on_live:   (symbol: str, tf: str, bar: OHLCVBar) -> None — 진행 중 봉(x=False, 약 0.3초마다).
                   2열 Coin Chart 실시간 표시 전용 (2026-11-23). None이면 진행 중 봉은 무시(기존 동작).
        """
        self._on_closed             = on_closed
        self._on_live               = on_live
        self._ws: websocket.WebSocketApp | None = None
        self._running               = False
        self._connected             = False
        self._last_data_time        = 0.0    # 마지막 마감 봉 수신 시각
        self._symbol                = ""
        self._conn_symbol           = ""     # 현재 연결(주소)의 심볼 — 연결 직후 _symbol과 다르면 닫고 다시 연결
        self._intentional_close     = False
        self._last_error: str       = ""
        self._last_error_time: float = 0.0
        self._thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def has_received_data(self) -> bool:
        """최근 _STALE_SEC 안에 실제 봉 마감 데이터를 받았는지 (연결 성공과 별개).
        끊김·데이터 없는 연결이 이어지면 False로 돌아가 선택 종목 REST 상세 갱신 대체가 다시 동작한다."""
        return time.time() - self._last_data_time < _STALE_SEC

    @property
    def last_error(self) -> str:
        return self._last_error

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
                self._ws.close()   # 의도적 종료 — _loop에서 딜레이 없이 즉시 재연결
            except Exception:
                pass

    def stop(self) -> None:
        """WebSocket 연결 종료."""
        self._running   = False
        self._connected = False
        if self._ws is not None:
            try:
                self._ws.close()   # 의도적 종료
            except Exception:
                pass

    # ── 내부 루프 ─────────────────────────────────────────────

    def _build_url(self, symbol: str = "") -> str:
        sym     = (symbol or self._symbol).lower()
        streams = "/".join(f"{sym}@kline_{tf}" for tf in _TFS)
        return f"wss://fstream.binance.com/market/stream?streams={streams}"

    def _loop(self) -> None:
        """재연결 자동화 루프."""
        while self._running:
            if not self._symbol:
                time.sleep(1)
                continue
            try:
                conn_sym = self._symbol
                self._conn_symbol = conn_sym
                self._ws = websocket.WebSocketApp(
                    self._build_url(conn_sym),
                    on_open    = self._on_open,
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self._last_error      = f"[klines:{self._symbol}] loop: {e}"
                self._last_error_time = time.time()
            finally:
                self._connected = False
            if self._running and not self._intentional_close:
                time.sleep(_RECONNECT_DELAY)
            self._intentional_close = False

    # ── WebSocket 이벤트 핸들러 ───────────────────────────────

    def _on_open(self, ws) -> None:
        # 연결 준비 중(WebSocketApp 생성 ~ run_forever 시작) 들어온 set_symbol()·stop()의 close()는 무시될 수 있다
        # (websocket-client run_forever가 시작할 때 keep_running=True로 되돌림) → 옛 심볼 연결이 남아 모든 메시지가
        # 버려지거나 종료 후에도 연결 유지. 연결 직후 다시 확인해 닫는다 (2026-11-25)
        if not self._running or self._conn_symbol != self._symbol:
            self._intentional_close = True   # 심볼 교체 — _loop가 대기 없이 새 심볼로 재연결
            ws.close()
            return
        self._connected = True

    def _on_close(self, ws, code, msg) -> None:
        self._connected = False

    def _on_error(self, ws, error) -> None:
        self._connected       = False
        self._last_error      = f"[klines:{self._symbol}] {error}"
        self._last_error_time = time.time()

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
            data    = payload.get("data", {})
            kline   = data.get("k", {})
            closed  = bool(kline.get("x", False))
            if not closed and self._on_live is None:   # 진행 중 봉 — 실시간 표시 콜백 없으면 무시 (기존 동작)
                return
            sym = data.get("s", "")
            tf  = kline.get("i", "")
            if sym and tf and sym == self._symbol:
                bar = OHLCVBar(
                    open_time=int(kline["t"]),
                    open=float(kline["o"]),
                    high=float(kline["h"]),
                    low=float(kline["l"]),
                    close=float(kline["c"]),
                    volume=float(kline["v"]),
                    quote_volume=float(kline["q"]),
                    close_time=int(kline["T"]),
                    taker_buy_volume=float(kline["V"]),
                )
                if not closed:
                    self._on_live(sym, tf, bar)   # 진행 중 봉 — 마감 기록(_last_data_time)·on_closed와 무관
                    return
                self._last_data_time = time.time()
                self._on_closed(sym, tf, bar)
        except Exception as e:
            err = f"[klines:{self._symbol}] msg: {e}"
            if err != self._last_error:   # 같은 오류 반복(진행 중 봉 약 0.3초마다)은 1번만 기록
                logging.warning("middle %s", err)
            self._last_error      = err
            self._last_error_time = time.time()
