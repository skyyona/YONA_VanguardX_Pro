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


class _Lbl:
    def __init__(self, text=""):
        self.cfg = {"text": text, "anchor": "w"}

    def configure(self, **kw):
        self.cfg.update(kw)


class _Popup:
    def destroy(self):
        pass


@pytest.mark.parametrize("mode,col4", [("Sharp rise", "Squeeze Str"), ("Volatility", "ATR%"),
                                       ("4TF Optimization", "4TF Score"), ("Newly Listed", "Listing Age"),
                                       ("24h Ticker", "M4 준비")])
def test_header_restored_after_pending(mode, col4):
    """Pending Listing → 다른 모드: col1~3 헤더 기본값 복원 (기존: 24h Ticker로 갈 때만 복원)."""
    p = MiddlePanel.__new__(MiddlePanel)
    p._sort_mode, p._sort_btn = "24h Ticker", None
    p._hdr_labels = [_Lbl() for _ in range(6)]
    p.after = lambda ms, fn=None, *a: None
    p._on_sort_mode_changed = lambda m: None
    p._rebuild_ranking_rows = lambda: None
    p._select_sort("Pending Listing", _Popup())
    assert p._hdr_labels[1].cfg["text"] == "심볼  [유형]"
    p._select_sort(mode, _Popup())
    assert [(l.cfg["text"], l.cfg["anchor"]) for l in p._hdr_labels[1:4]] == [
        ("Coin Symbol", "w"), ("Change%", "e"), ("Cumulative", "e")]
    assert p._hdr_labels[4].cfg["text"] == col4


def test_settling_double_click_opens_symbol(root, monkeypatch):
    """Settling 더블클릭 → 심볼 칸 값으로 바이낸스 열기 (기존: 체크 칸 "☐"), 안내 행은 무시."""
    from tkinter import ttk
    from middle.data.settling import SettlingEntry
    opened = []
    monkeypatch.setattr(_ctx, "_bl_mgr", None)
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    monkeypatch.setattr(MiddlePanel, "_open_binance", staticmethod(lambda s: opened.append(s)))
    p = MiddlePanel.__new__(MiddlePanel)
    p._checked_settling = set()
    tree = ttk.Treeview(root, columns=("n", "chk", "sym", "chg", "st"), show="headings")
    p._settling_cache = [SettlingEntry("XUSDT", "SETTLING", "Settling", "ora")]
    p._render_settling_tree(tree)
    tree.focus(tree.get_children()[0])
    p._open_settling_symbol(tree)
    assert opened == ["XUSDT"]
    p._settling_cache = []
    p._render_settling_tree(tree)                       # "감지된 심볼 없음" 안내 행
    tree.focus(tree.get_children()[0])
    p._open_settling_symbol(tree)
    assert opened == ["XUSDT"]
