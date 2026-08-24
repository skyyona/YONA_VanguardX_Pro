"""
tests/middle/test_data_manager_fallback.py
A-1 WebSocket 폴백 조건 단위 테스트 — 네트워크·타이머 무의존.

폴백 로직 (data_manager.py STAGE3 내):
  if _ws_klines is None or not _ws_klines.has_received_data:
      with self._lock:
          _fallback_sym = self._last_detail_sym
      if _fallback_sym:
          _ws_err = _ws_klines.last_error if _ws_klines is not None else ""
          if _ws_err:
              with self._lock:
                  self._last_refresh_error      = _ws_err
                  self._last_refresh_error_time = time.time()
          self.request_selected(_fallback_sym)
"""
import types
import sys

# websocket-client stub (WebSocketKlines import 의존)
_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from middle.data.data_manager import MiddleDataManager


def _make_dm() -> MiddleDataManager:
    """네트워크 호출 없이 MiddleDataManager 인스턴스 생성."""
    return MiddleDataManager()


def _run_fallback(dm: MiddleDataManager, called: list) -> None:
    """STAGE3 폴백 블록을 인라인으로 재현 (루프·타이머 없이).
    request_selected 는 monkey-patch로 교체해 내부 WS 호출을 차단한다.
    """
    _orig = dm.request_selected
    dm.request_selected = lambda sym: called.append(sym)
    try:
        dm_ws = dm._ws_klines
        if dm_ws is None or not dm_ws.has_received_data:
            with dm._lock:
                _fallback_sym = dm._last_detail_sym
            if _fallback_sym:
                dm.request_selected(_fallback_sym)
    finally:
        dm.request_selected = _orig


# ── T-7 ──────────────────────────────────────────────────────────────────────

def test_t7_fallback_fires_when_no_ws_data():
    """has_received_data=False 일 때 폴백이 발동하여 request_selected 가 호출된다."""
    dm = _make_dm()

    mock_ws = types.SimpleNamespace(has_received_data=False, last_error="")
    dm._ws_klines        = mock_ws
    dm._last_detail_sym  = "BTCUSDT"
    dm._last_detail_time = 0.0

    called = []
    _run_fallback(dm, called)

    assert called == ["BTCUSDT"]


# ── T-8 ──────────────────────────────────────────────────────────────────────

def test_t8_no_fallback_when_ws_receiving():
    """has_received_data=True 일 때 폴백이 발동하지 않는다."""
    dm = _make_dm()

    mock_ws = types.SimpleNamespace(has_received_data=True, last_error="")
    dm._ws_klines        = mock_ws
    dm._last_detail_sym  = "BTCUSDT"
    dm._last_detail_time = 0.0

    called = []
    _run_fallback(dm, called)

    assert called == []


# ── T-9 ──────────────────────────────────────────────────────────────────────

def test_t9_no_fallback_when_no_selected_symbol():
    """_last_detail_sym 이 빈 문자열이면 폴백이 발동하지 않는다."""
    dm = _make_dm()

    mock_ws = types.SimpleNamespace(has_received_data=False, last_error="")
    dm._ws_klines        = mock_ws
    dm._last_detail_sym  = ""        # 선택 심볼 없음
    dm._last_detail_time = 0.0

    called = []
    _run_fallback(dm, called)

    assert called == []
