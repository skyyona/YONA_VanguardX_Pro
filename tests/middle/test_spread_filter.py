"""
tests/middle/test_spread_filter.py
배정 단계 호가 스프레드 필터 9건 — bookTicker 표본 → 최근 10개 중앙값 → 기준(0.2%) 초과 시 Assign 차단.
네트워크 무의존(bookTicker 응답만 대역).
"""
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

import pytest

import middle.widget.shared_context as _ctx
from middle.data import data_manager as _dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.widget.panel_col3 import _Col3Mixin


def _book(sym: str, bid: float, ask: float) -> dict:
    return {"symbol": sym, "bidPrice": str(bid), "askPrice": str(ask)}


def _dm(*snapshots: list) -> MiddleDataManager:
    """snapshots를 순서대로 돌려주는 bookTicker 대역으로 표본 수집."""
    dm = MiddleDataManager()
    queue = list(snapshots)
    dm._client = types.SimpleNamespace(fetch_all_book_tickers=lambda: queue.pop(0))
    for _ in snapshots:
        dm._refresh_spreads()
    return dm


def test_spread_pct_uses_mid():
    """스프레드(%) = (ask − bid) / mid × 100."""
    dm = _dm([_book("AUSDT", 99.9, 100.1)])
    assert dm.get_spread_median("AUSDT") == pytest.approx(0.2)


def test_median_resists_single_spike():
    """순간 확대 1회는 중앙값에 반영되지 않음."""
    dm = _dm([_book("AUSDT", 100.0, 100.02)], [_book("AUSDT", 100.0, 101.0)], [_book("AUSDT", 100.0, 100.02)])
    assert dm.get_spread_median("AUSDT") == pytest.approx(0.02, rel=1e-3)


def test_keeps_only_last_samples():
    """심볼별 최근 _SPREAD_SAMPLES개만 보관 — 오래된 넓은 표본은 밀려남."""
    wide   = [[_book("AUSDT", 100.0, 101.0)]] * 3
    narrow = [[_book("AUSDT", 100.0, 100.01)]] * _dm_mod._SPREAD_SAMPLES
    dm = _dm(*wide, *narrow)
    assert len(dm._spread_hist["AUSDT"]) == _dm_mod._SPREAD_SAMPLES
    assert dm.get_spread_median("AUSDT") == pytest.approx(0.01, rel=1e-3)


def test_invalid_rows_skipped_and_failure_keeps_samples():
    """bid 0·ask<bid·숫자 아님·심볼 없음 무시, 조회 실패(빈 목록)는 기존 표본 유지."""
    dm = _dm(
        [_book("AUSDT", 100.0, 100.1), _book("BUSDT", 0.0, 1.0), _book("CUSDT", 2.0, 1.0),
         {"symbol": "DUSDT", "bidPrice": "x", "askPrice": "1"}, _book("", 1.0, 1.1)],
        [],
    )
    assert set(dm._spread_hist) == {"AUSDT"}
    assert dm.get_spread_median("AUSDT") is not None
    assert dm.get_spread_median("ZUSDT") is None


def test_stop_clears_samples():
    """STOP 시 표본 초기화 — 재START 후 새 표본만 사용."""
    dm = _dm([_book("AUSDT", 100.0, 100.1)])
    dm.stop_auto_refresh()
    assert dm.get_spread_median("AUSDT") is None


@pytest.fixture()
def ctx_dm(monkeypatch):
    def _set(dm):
        monkeypatch.setattr(_ctx, "_data_mgr", dm)
        monkeypatch.setattr(_ctx, "_bl_mgr", None)
    return _set


def test_wide_spread_threshold(ctx_dm):
    """기준 0.2% 초과만 해당 — 정확히 0.2%·표본 없음은 None."""
    ctx_dm(_dm([_book("AUSDT", 99.85, 100.15), _book("BUSDT", 99.9, 100.1)]))
    assert _ctx.get_wide_spread("AUSDT") == pytest.approx(0.3)
    assert _ctx.get_wide_spread("BUSDT") is None
    assert _ctx.get_wide_spread("ZUSDT") is None


class _Panel(_Col3Mixin):
    """_on_assign이 쓰는 속성만 가진 대역 (Tk 미사용)."""

    def __init__(self):
        self._assigned_sym = None
        self._shared_sym = types.SimpleNamespace(value="", set=lambda v: setattr(self._shared_sym, "value", v))
        self.messages: list[str] = []

    def _set_header_message(self, msg: str) -> None:
        self.messages.append(msg)

    def _refresh_header(self) -> None:
        pass


def test_assign_blocked_on_wide_spread(ctx_dm):
    """스프레드 0.3% → 배정 차단 + 사유 메시지, 하단 전달 없음."""
    ctx_dm(_dm([_book("AUSDT", 99.85, 100.15)]))
    p = _Panel()
    p._on_assign("AUSDT")
    assert p._assigned_sym is None
    assert p._shared_sym.value == ""
    assert p.messages and "0.300%" in p.messages[0] and "0.2%" in p.messages[0]


def test_assign_allowed_on_normal_spread(ctx_dm):
    """스프레드 0.02% → 정상 배정."""
    ctx_dm(_dm([_book("AUSDT", 100.0, 100.02)]))
    p = _Panel()
    p._on_assign("AUSDT")
    assert p._assigned_sym == "AUSDT"
    assert p._shared_sym.value == "AUSDT"
    assert p.messages == []


def test_assign_allowed_without_samples(ctx_dm):
    """표본 없음(시작 직후·조회 실패) → 차단하지 않음."""
    ctx_dm(_dm())
    p = _Panel()
    p._on_assign("AUSDT")
    assert p._assigned_sym == "AUSDT"
