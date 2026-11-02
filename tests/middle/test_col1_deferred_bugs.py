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


_PENDING_RAW = [({"symbol": "AAAUSDT", "baseAsset": "AAA", "onboardDate": 300,
                  "underlyingType": "COIN", "underlyingSubType": ["DeFi"]}, {"markPrice": "1.5"})]


class _SlowDM:
    """조회 1회 0.4초 — 화면 스레드에서 호출되면 그만큼 멈춤. result=None이면 조회 실패."""

    def __init__(self, pending=None, info=None):
        self.pending, self.info, self.threads = pending, info, []

    def fetch_pending_listings(self):
        import threading
        self.threads.append(threading.current_thread() is threading.main_thread())
        time.sleep(0.4)
        return self.pending

    def fetch_exchange_info(self):
        import threading
        self.threads.append(threading.current_thread() is threading.main_thread())
        time.sleep(0.4)
        return self.info

    def get_ticker(self, sym):
        return None


def _pending_panel(root, monkeypatch, dm):
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    p._sort_mode = "Pending Listing"
    p._pending_cache, p._pending_status, p._pending_after_id = [], "loading", None
    p._inner = tk.Frame(root)
    p._row_frames, p._special = [], {}
    p.rebuilds = 0
    def _rebuild():
        p.rebuilds += 1
    p._rebuild_ranking_rows = _rebuild
    return p


def _wait(root, cond, limit=3.0):
    """실제 mainloop 실행 — 작업 스레드의 after(0, ...) 전달은 메인 스레드가 mainloop 중일 때만 동작(실제 앱과 동일)."""
    end = time.time() + limit
    def _check():
        if cond() or time.time() > end:
            root.quit()
        else:
            root.after(20, _check)
    root.after(20, _check)
    root.mainloop()


def test_pending_load_in_worker_then_main_thread_apply(root, monkeypatch):
    dm = _SlowDM(pending=_PENDING_RAW)
    p = _pending_panel(root, monkeypatch, dm)
    t0 = time.time()
    p._load_pending_then_rebuild()
    assert time.time() - t0 < 0.2                  # 화면 스레드 대기 없음
    assert p._pending_status == "loading"
    _wait(root, lambda: p._pending_status != "loading")
    assert dm.threads == [False]                   # 조회는 작업 스레드
    assert p._pending_status == "ok" and [e.symbol for e in p._pending_cache] == ["AAAUSDT"]
    assert p.rebuilds == 1


def test_pending_failure_shows_failed_not_empty(root, monkeypatch):
    p = _pending_panel(root, monkeypatch, _SlowDM(pending=None))
    p._load_pending_then_rebuild()
    _wait(root, lambda: p._pending_status != "loading")
    assert p._pending_status == "failed"
    p._build_pending_rows()
    texts = [w.cget("text") for f in p._inner.winfo_children() for w in f.winfo_children()]
    assert "  PENDING 조회 실패 — Sort by에서 Pending Listing을 다시 선택하면 재조회합니다." in texts


def test_pending_reentry_keeps_single_60s_timer(root, monkeypatch):
    """Pending 재진입 시 이전 60초 예약 취소 (기존: 재진입마다 갱신 체인 누적)."""
    p = _pending_panel(root, monkeypatch, _SlowDM(pending=[]))
    p._schedule_pending_refresh()
    first = p._pending_after_id
    p._schedule_pending_refresh()
    pending_ids = root.tk.splitlist(root.tk.call("after", "info"))
    assert first not in pending_ids and p._pending_after_id in pending_ids


def test_settling_load_in_worker_and_failure_message(root, monkeypatch):
    from tkinter import ttk
    from middle.data.settling import SettlingDetector
    monkeypatch.setattr(_ctx, "_bl_mgr", None)
    info = {"symbols": [{"symbol": "EEEUSDT", "status": "SETTLING"}]}
    for dm, status in ((_SlowDM(info=info), "ok"), (_SlowDM(info=None), "failed")):
        monkeypatch.setattr(_ctx, "_data_mgr", dm)
        p = MiddlePanel.__new__(MiddlePanel)
        tk.Frame.__init__(p, root)
        p._checked_settling, p._settling_cache, p._settling_status = set(), [], "loading"
        p._t_tree = ttk.Treeview(root, columns=("n", "chk", "sym", "chg", "st"), show="headings")
        t0 = time.time()
        p._load_settling_data()
        assert time.time() - t0 < 0.2                                      # 화면 스레드 대기 없음
        assert p._t_tree.item(p._t_tree.get_children()[0], "values")[2] == "Settling 조회 중..."
        _wait(root, lambda: p._settling_status != "loading")
        assert dm.threads == [False] and p._settling_status == status
        sym_col = [p._t_tree.item(i, "values")[2] for i in p._t_tree.get_children()]
        if status == "ok":
            assert sym_col == [e.symbol for e in SettlingDetector.detect(info)]
        else:
            assert sym_col == ["Settling 조회 실패 — 앱 재시작 시 다시 조회"]
