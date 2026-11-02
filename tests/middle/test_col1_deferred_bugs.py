"""
tests/middle/test_col1_deferred_bugs.py
1열 정리 4단계 — 미뤄 둔 버그 수정 검증 (실제 Tk 타이머·위젯 경로, 데이터 관리자는 대역).
"""
import time
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.widget.middle_panel import MiddlePanel


@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.withdraw()
    yield r
    r.destroy()


def _pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def _timer_panel(root, monkeypatch):
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._time_fixed, p._time_fix_prices, p._row_frames = False, {}, []
    p._timefix_btn = p._timer_lbl = None
    p._timer_running, p._elapsed_sec, p._tick_after_id = False, 0, None
    p._rebuild_ranking_rows = lambda: None
    p._update_cum_labels = lambda: None
    p._on_time_fix_tick = lambda: None
    return p


def test_time_fix_quick_retoggle_keeps_single_timer(root, monkeypatch):
    """Time Fix 켬 → 해제 → 1초 안에 다시 켬: 타이머 1개만 (기존: 이전 예약 틱이 살아 2배속)."""
    p = _timer_panel(root, monkeypatch)
    p._toggle_time_fix()           # 켬 — 즉시 1틱
    _pump(root, 0.3)
    p._toggle_time_fix()           # 해제
    p._toggle_time_fix()           # 1초 안에 다시 켬 — 즉시 1틱
    _pump(root, 2.5)               # 이후 2틱 (1초 간격)
    assert p._elapsed_sec == 3
    p._toggle_time_fix()
    _pump(root, 1.2)
    assert p._elapsed_sec == 0 and p._tick_after_id is None
