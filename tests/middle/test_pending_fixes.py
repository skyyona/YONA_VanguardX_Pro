"""
tests/middle/test_pending_fixes.py
1열 Sort by 'Pending Listing' 결함 수정 (2026-11-16) — 네트워크 없이 대역.
 A  START 전(IDLE) 조회·타이머 없음, START 시 새로 조회, STOP 시 타이머 중지
 P1 예정일 경과 = '예정일 경과'(상장됨 아님) · 예정일 미상 '—'·맨 뒤
 P2 진입 시 '로드 중'으로 먼저 바꾼 뒤 재빌드 · P5 가장 최근 조회 결과만 반영
 P3 5분마다 재조회(기존 목록 유지, 실패 시 유지) · P4 유형 배지 underlyingType 기준
 P6 종목별 파싱 오류 격리 · P7 남은 시간 정수 계산 · P8 클릭해도 선택 종목으로 남지 않음 · P9 KST 표시
"""
import datetime
import time
import types
from zoneinfo import ZoneInfo

import pytest

import middle.widget.shared_context as _ctx
from middle.col1_ranking.ranking.pending_listing import PendingEntry, PendingListingDetector as P
from middle.widget.middle_panel import MiddlePanel


def _e(ut="COIN", sub=(), ob=0):
    return PendingEntry("XUSDT", "X", ob, ut, list(sub), 0.0)


# ── P1·P7 남은 시간 ────────────────────────────────────────────────────
@pytest.mark.parametrize("delta_ms, text", [
    (-1, "예정일 경과"),                      # 수정 전: '상장됨' (PENDING_TRADING인데)
    (-365 * 86_400_000, "예정일 경과"),       # 실측 GAIB: 예정일 1년 경과·여전히 PENDING
    (30_000, "1분 미만"),                     # 수정 전: '0분 후'
    (5 * 60_000 + 500, "5분 후"),
    (61 * 60_000 + 500, "1h 1m 후"),          # 수정 전: '1h 0m 후' (부동소수 분 손실)
    (121 * 60_000 + 500, "2h 1m 후"),
    ((47 * 60 + 59) * 60_000 + 500, "1일 23h 후"),   # 수정 전: '1일 후'
    (3 * 86_400_000 + 5 * 3_600_000 + 500, "3일 5h 후"),
])
def test_p1_p7_format_remaining(monkeypatch, delta_ms, text):
    now = 1_800_000_000_000
    monkeypatch.setattr("middle.col1_ranking.ranking.pending_listing.time.time", lambda: now / 1000)
    assert P.format_remaining(now + delta_ms)[0] == text


def test_p1_unknown_onboard_date():
    assert P.format_remaining(0) == ("—", "#666666")       # 수정 전: '상장됨'


def test_p1_missing_onboard_sorted_last():
    from middle.data.data_manager import MiddleDataManager
    dm = MiddleDataManager()
    dm._client = types.SimpleNamespace(
        fetch_exchange_info=lambda: {"symbols": [
            {"symbol": "NOODUSDT", "status": "PENDING_TRADING"},
            {"symbol": "BUSDT", "status": "PENDING_TRADING", "onboardDate": 2000},
            {"symbol": "AUSDT", "status": "PENDING_TRADING", "onboardDate": 1500}]},
        fetch_mark_price=lambda s: None)
    assert [s["symbol"] for s, _ in dm.fetch_pending_listings()] == ["AUSDT", "BUSDT", "NOODUSDT"]


# ── P4 유형 배지 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("ut, sub, badge", [
    ("EQUITY", ["TradFi"], "[주식]"), ("EQUITY", [], "[주식]"), ("HK_EQUITY", ["TradFi"], "[주식]"),
    ("CN_EQUITY", ["TradFi"], "[주식]"), ("KR_EQUITY", ["TradFi"], "[주식]"),
    ("COMMODITY", ["TradFi"], "[원자재]"), ("PREMARKET", ["Pre-IPO", "TradFi"], "[프리마켓]"),
    ("INDEX", [], "[지수]"), ("FX", ["TradFi"], "[FX]"),
    ("COIN", ["DeFi", "Crypto"], "[DeFi]"), ("COIN", ["Layer-1"], "[COIN]"),
])
def test_p4_badge_by_underlying_type(ut, sub, badge):
    assert P.get_type_badge(_e(ut, sub))[0] == badge        # 수정 전: HK·CN·INDEX·FX·TradFi 없는 EQUITY → [COIN]


# ── P6 종목별 파싱 오류 격리 ───────────────────────────────────────────
def test_p6_bad_entry_does_not_cut_list():
    raw = [({"symbol": "AUSDT", "onboardDate": 1}, {"markPrice": "1.5"}),
           ({"symbol": "BUSDT", "onboardDate": 2}, {"markPrice": "abc"}),          # 형식 오류
           ({"symbol": "CUSDT", "onboardDate": 3, "underlyingSubType": None}, None),
           ({"onboardDate": 4}, None),                                              # symbol 없음
           ({"symbol": "DUSDT", "onboardDate": 5}, {"markPrice": ""})]
    out = P.parse(raw)
    assert [e.symbol for e in out] == ["AUSDT", "CUSDT", "DUSDT"]   # 수정 전: ['AUSDT'] (B에서 중단)
    assert out[1].underlying_sub == [] and out[2].mark_price == 0.0


# ── A·P2·P3·P5 로드 흐름 (Tk) ─────────────────────────────────────────
@pytest.fixture()
def root():
    import tkinter as tk
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.withdraw()
    yield r
    r.destroy()


class _DM:
    def __init__(self, results):
        self.results, self.calls = list(results), 0

    def fetch_pending_listings(self):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, tuple):                 # (지연 초, 결과)
            time.sleep(r[0])
            r = r[1]
        return r


_RAW = lambda sym: [({"symbol": sym, "onboardDate": 1}, None)]


def _panel(root, monkeypatch, dm, state="RANKING"):
    import tkinter as tk
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    p = MiddlePanel.__new__(MiddlePanel)
    tk.Frame.__init__(p, root)
    import queue
    p._ui_queue = queue.Queue()
    p._sort_mode, p._app_state = "Pending Listing", state
    p._pending_cache, p._pending_status, p._pending_after_id = [], "ok", None
    p.rebuilds = []
    p._rebuild_ranking_rows = lambda: p.rebuilds.append((p._pending_status, [e.symbol for e in p._pending_cache]))
    return p


def _drain_until(root, p, cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        while not p._ui_queue.empty():
            fn, args = p._ui_queue.get_nowait()
            fn(*args)
        root.update()
        time.sleep(0.01)
    assert cond()


def test_a_idle_no_fetch_no_timer(root, monkeypatch):
    dm = _DM([_RAW("AUSDT")])
    p = _panel(root, monkeypatch, dm, state="IDLE")
    p._start_pending_load()
    time.sleep(0.1)
    assert dm.calls == 0 and p._pending_after_id is None     # 수정 전: START 전에도 조회·타이머


def test_a_start_fetches_fresh_and_stop_cancels(root, monkeypatch):
    dm = _DM([_RAW("NEWUSDT")])
    p = _panel(root, monkeypatch, dm, state="IDLE")
    p._pending_cache = P.parse(_RAW("OLDUSDT"))              # START 전에 남은 옛 목록
    p.after_cancel = lambda i: None
    p._set_header_message = lambda m: None
    p._data_ready_after_ids = {}
    import middle.widget.middle_panel as mp
    monkeypatch.setattr(mp, "_data_mgr", None)
    p.on_app_start()
    assert p.rebuilds[0] == ("loading", [])                  # 수정 전: 옛 목록(OLDUSDT) 표시, 새 조회 없음
    _drain_until(root, p, lambda: dm.calls == 1 and p._pending_status == "ok")
    assert [e.symbol for e in p._pending_cache] == ["NEWUSDT"] and p._pending_after_id is not None
    p._stop_chart_timer = p._stop_analysis_timer = p._clear_analysis_panels = lambda: None
    p._clear_btn = None
    del p.after_cancel
    p.on_app_stop()
    assert p._pending_after_id is None                       # STOP → 1분 타이머 중지


def test_p2_reentry_shows_loading_not_old_list(root, monkeypatch):
    dm = _DM([(0.3, _RAW("NEWUSDT"))])
    p = _panel(root, monkeypatch, dm)
    p._pending_cache = P.parse(_RAW("OLDUSDT"))
    p._start_pending_load()
    assert (p._pending_status, p._pending_cache) == ("loading", [])   # 재빌드 전 '로드 중' (수정 전: 옛 목록 그대로)
    _drain_until(root, p, lambda: p._pending_status == "ok")
    assert p.rebuilds[-1] == ("ok", ["NEWUSDT"])


def test_p5_only_latest_fetch_applied(root, monkeypatch):
    dm = _DM([(0.5, None), (0.05, _RAW("NEWUSDT"))])          # 먼저 시작한 느린 조회 실패, 나중 조회 성공
    p = _panel(root, monkeypatch, dm)
    p._load_pending_then_rebuild(clear=True)
    p._load_pending_then_rebuild(clear=True)
    _drain_until(root, p, lambda: dm.calls == 2 and p._pending_status == "ok")
    time.sleep(0.6)
    _drain_until(root, p, lambda: p._ui_queue.empty())
    assert p._pending_status == "ok" and [e.symbol for e in p._pending_cache] == ["NEWUSDT"]   # 수정 전: 'failed'


def test_p3_refetch_every_5_ticks_keeps_list_on_failure(root, monkeypatch):
    dm = _DM([_RAW("AUSDT"), None])
    p = _panel(root, monkeypatch, dm)
    p._start_pending_load()
    _drain_until(root, p, lambda: p._pending_status == "ok")
    for _ in range(4):                                       # 1~4분: 남은 시간만 갱신
        p._do_pending_time_refresh()
    assert dm.calls == 1
    p._do_pending_time_refresh()                             # 5분: 재조회 (실패)
    _drain_until(root, p, lambda: dm.calls == 2 and p._ui_queue.empty())
    time.sleep(0.05)
    _drain_until(root, p, lambda: p._ui_queue.empty())
    assert p._pending_status == "ok" and [e.symbol for e in p._pending_cache] == ["AUSDT"]   # 실패해도 기존 목록 유지
    p._cancel_pending_refresh()


def test_p3_timer_stops_when_idle_or_mode_changed(root, monkeypatch):
    p = _panel(root, monkeypatch, _DM([]))
    p._app_state = "IDLE"
    p._do_pending_time_refresh()
    assert p._pending_after_id is None and p.rebuilds == []


# ── P8 클릭해도 선택 종목으로 남지 않음 ─────────────────────────────────
def test_p8_click_does_not_set_selected_symbol(root, monkeypatch):
    import tkinter as tk
    p = _panel(root, monkeypatch, _DM([]))
    p._sel_var = tk.StringVar(root, "BTCUSDT")
    p._sel_idx = -1
    p._row_frames = [(tk.Frame(root), "GAIBUSDT")]
    p._special = {0: set()}
    p._on_select("GAIBUSDT", 0)
    assert p._sel_var.get() == "BTCUSDT"                    # 수정 전: 'GAIBUSDT'
    assert p._row_frames[0][0].cget("highlightthickness") == 1   # 강조 표시는 유지


# ── P9 KST 표시 ───────────────────────────────────────────────────────
def test_p9_listing_time_shown_in_kst(root, monkeypatch):
    import tkinter as tk
    ob = 1_763_629_200_000                                   # 2025-11-20 09:00 UTC = 18:00 KST
    p = _panel(root, monkeypatch, _DM([]))
    p._inner = tk.Frame(root)
    p._row_frames, p._special = [], {}
    p._on_select = lambda s, i: None
    p._bind_row_children = lambda *a, **k: None
    p._pending_cache = P.parse([({"symbol": "GAIBUSDT", "baseAsset": "GAIB", "onboardDate": ob}, None)])
    p._build_pending_rows()
    texts = []
    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                texts.append(c.cget("text"))
            walk(c)
    walk(p._inner)
    assert "11/20 18:00" in texts and "예정일 경과" in texts and "상장됨" not in texts
    assert datetime.datetime.fromtimestamp(ob / 1000, ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M") == "11/20 18:00"
