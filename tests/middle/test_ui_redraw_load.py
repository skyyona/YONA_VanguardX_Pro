"""
tests/middle/test_ui_redraw_load.py
화면 스레드 부하 감소 (2026-11-03 py-spy 실측 기반) —
① 2열 차트: 앱 전체 배치 강제(update_idletasks) 없이 차트 프레임 크기로 그리기, 배치 전이면 Configure 후 다시 그림
② 상세 갱신 완료 → 2열·3열 재생성: 같은 종목 0.3초 안 연속 완료는 1번으로 묶음 (종목별)
③ Time Fix 누적%: 표시 값이 바뀐 행만 configure
"""
import time
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
import middle.widget.middle_panel as mp_mod
from middle.widget.middle_panel import MiddlePanel


@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.geometry("400x300+0+0")
    yield r
    r.destroy()


def _run(root, seconds):
    root.after(int(seconds * 1000), root.quit)
    root.mainloop()


def _run_until(root, cond, limit=5.0):
    """cond() 참이 될 때까지 mainloop (창 배치 시간은 PC 부하에 따라 다름)."""
    end = time.time() + limit
    def _check():
        if cond() or time.time() > end:
            root.quit()
        else:
            root.after(20, _check)
    root.after(20, _check)
    root.mainloop()


# ── ① 2열 차트 ──────────────────────────────────────────────
def _chart_panel(root, monkeypatch):
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._chart_f = tk.Frame(root, width=300, height=200)
    p._sel_var, p._tf_var = tk.StringVar(root, "XUSDT"), tk.StringVar(root, "5분봉")
    p.idle_calls = 0
    def _count():
        p.idle_calls += 1
    p.update_idletasks = _count
    return p


def _canvas_text(p):
    cv = p._chart_f.winfo_children()[0]
    return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]


def test_chart_fallback_uses_frame_size_without_forcing_layout(root, monkeypatch):
    p = _chart_panel(root, monkeypatch)
    p._chart_f.pack(fill="both", expand=True)
    _run_until(root, lambda: p._chart_f.winfo_ismapped() and p._chart_f.winfo_width() > 1)   # 프레임 배치 완료
    p._draw_canvas_fallback()
    assert p.idle_calls == 0                          # 기존: 매번 update_idletasks()
    assert _canvas_text(p) == ["XUSDT\n데이터 로드 중..."]
    cv = p._chart_f.winfo_children()[0]
    t = cv.find_all()[0]
    assert cv.coords(t) == [p._chart_f.winfo_width() // 2, p._chart_f.winfo_height() // 2]


def test_chart_fallback_before_layout_redraws_on_configure(root, monkeypatch):
    p = _chart_panel(root, monkeypatch)
    redraws = []
    p._refresh_chart = lambda: redraws.append(1)
    p._draw_canvas_fallback()                         # 프레임 배치 전 (크기 1)
    assert p._chart_f.winfo_children()[0].find_all() == ()
    p._chart_f.pack(fill="both", expand=True)
    _run_until(root, lambda: bool(redraws))
    assert redraws                                    # 배치되면 실제 크기로 다시 그림
    assert p.idle_calls == 0


# ── ② 상세 갱신 묶기 ─────────────────────────────────────────
def _ready_panel(root, sel="AUSDT"):
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._sel_var, p._app_state, p._cur_chart_tab = tk.StringVar(root, sel), "ANALYSIS", "chart"
    p._data_ready_after_ids = {}
    p.detail, p.chart = [], []
    p._do_refresh_detail = lambda: p.detail.append(time.time())
    p._refresh_chart = lambda: p.chart.append(time.time())
    return p


def test_data_ready_burst_coalesced_to_single_refresh(root):
    """봉 경계처럼 같은 종목 상세 갱신 4번이 연달아 와도 2열·3열 재생성 1번 (기존: 4번)."""
    p = _ready_panel(root)
    for _ in range(4):
        p._on_data_ready("AUSDT")
    _run(root, (mp_mod._DATA_READY_COALESCE_MS + 300) / 1000)
    assert len(p.detail) == 1 and len(p.chart) == 1


def test_data_ready_other_symbol_does_not_cancel_selected(root):
    """엔진 종목(다른 심볼) 갱신 완료가 선택 종목 재생성 예약을 지우지 않음."""
    p = _ready_panel(root)
    p._on_data_ready("AUSDT")
    p._on_data_ready("ENGUSDT")
    _run(root, (mp_mod._DATA_READY_COALESCE_MS + 300) / 1000)
    assert len(p.detail) == 1


def test_data_ready_separated_calls_each_refresh(root):
    p = _ready_panel(root)
    p._on_data_ready("AUSDT")
    _run(root, (mp_mod._DATA_READY_COALESCE_MS + 200) / 1000)
    p._on_data_ready("AUSDT")
    _run(root, (mp_mod._DATA_READY_COALESCE_MS + 200) / 1000)
    assert len(p.detail) == 2


# ── ③ Time Fix 누적% ────────────────────────────────────────
class _Lbl:
    def __init__(self):
        self.n = 0
        self.cfg = {}

    def configure(self, **kw):
        self.n += 1
        self.cfg.update(kw)


class _Tkr:
    def __init__(self, price):
        self.last_price = price


def test_cum_labels_configure_only_changed(monkeypatch):
    prices = {"AUSDT": 101.0, "BUSDT": 50.0}
    monkeypatch.setattr(_ctx, "_data_mgr", type("DM", (), {"get_ticker": lambda self, s: _Tkr(prices[s])})())
    p = MiddlePanel.__new__(MiddlePanel)
    la, lb = _Lbl(), _Lbl()
    p._cum_labels = {"AUSDT": (la, "", ""), "BUSDT": (lb, "", "")}
    p._cum_shown = {}
    p._time_fixed, p._time_fix_prices = True, {"AUSDT": 100.0, "BUSDT": 50.0}
    p._update_cum_labels()
    assert (la.n, lb.n) == (1, 1) and la.cfg["text"] == "+1.00%" and lb.cfg["text"] == "+0.00%"
    p._update_cum_labels()                               # 가격 그대로 → configure 없음 (기존: 매초 전 행)
    assert (la.n, lb.n) == (1, 1)
    prices["AUSDT"] = 102.0
    p._update_cum_labels()
    assert (la.n, lb.n) == (2, 1) and la.cfg["text"] == "+2.00%"
    p._time_fixed = False
    p._update_cum_labels()
    assert la.cfg["text"] == lb.cfg["text"] == "+000.00"
