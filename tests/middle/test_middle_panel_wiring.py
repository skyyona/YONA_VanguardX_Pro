"""
tests/middle/test_middle_panel_wiring.py
중단 패널 열 간 연결 동작 고정 — Sort by 전환(1열 → 2·3열), Time Fix 30초 상세 갱신,
Assign(3열 버튼 → 하단 엔진 공유 심볼), 4TF 종합분석 판정 렌더링.
MiddlePanel 조합 클래스를 __init__ 없이 생성하고 위젯·타이머·데이터 관리자는 기록용 대역으로 대체
→ 메서드가 어느 믹스인 파일에 있든 같은 동작인지 검증한다.
"""
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.data.data_manager import MiddleDataManager
from middle.analysis.forecast import Forecaster
from middle.widget.middle_panel import MiddlePanel

_MODES = ["24h Ticker", "Sharp rise", "Sharp decline", "Volatility",
          "4TF Optimization", "Newly Listed", "Pending Listing"]


class _Lbl:
    def __init__(self):
        self.cfg = {}

    def configure(self, **kw):
        self.cfg.update(kw)


class _Var:
    def __init__(self, v=""):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class _Popup:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class _DM:
    """MiddleDataManager 대역 — 패널이 쓰는 조회·요청 메서드만."""

    def __init__(self, ind=None, rows=None, fail=False):
        self.ind, self.rows, self.fail = ind or {}, rows or [], fail
        self.requested: list[str] = []
        self._vol_rank = {r[0]: i + 1 for i, r in enumerate(self.rows)}   # 현재 거래량 순위 (4TF 거래량Top10)

    def ind_ready(self, sym):     # 채점용 실제 지표 여부 — 대역 지표는 실제 값으로 취급
        return sym in self.ind

    def engine_atr_band(self, mode="Volatility"):
        return (1.85, 6.0)

    def engine_k_gate(self, mode="4TF Optimization"):
        return (35.0, 65.0)

    def get_ind(self, sym):
        return self.ind.get(sym, {})

    def get_ranking_rows(self):
        return self.rows

    def get_row(self, sym):   # 1열 행 단일 정의 대역 — 시세가 있는 종목(여기선 랭킹 행)만 행 반환
        return next((r for r in self.rows if r[0] == sym), None)

    def get_newlisted_rows(self):
        return []

    def request_selected(self, sym):
        if self.fail:
            raise RuntimeError("request 실패")
        self.requested.append(sym)

    def get_spread_median(self, sym):
        return None

    get_player = MiddleDataManager.get_player   # Player 판정 단일 정의 (get_ind 기반)
    _ind_fresh = lambda self, sym: True          # 대역 지표 = 갱신 대상 값 (MiddleDataManager._ind_fresh)
    _forecaster = Forecaster(None)   # 가격 예고 판정식 없음 → 3열 '판정식 없음' 표시

    def get_forecast(self, sym):
        return None

    def get_listing_days(self, sym):
        return 0


class _BL:
    def __init__(self, syms=()):
        self.syms = set(syms)

    def is_blacklisted(self, sym):
        return sym in self.syms

    def get_all(self):
        return self.syms


def _panel(**attrs) -> MiddlePanel:
    """호출 기록(p.calls)을 남기는 MiddlePanel — Tk 위젯 없음."""
    p = MiddlePanel.__new__(MiddlePanel)
    p.calls = []
    p.after = lambda ms, fn=None, *a: p.calls.append(("after", ms, fn.__name__))
    p._switch_chart_tab = lambda key: p.calls.append(("tab", key))
    p._refresh_verdict = lambda: p.calls.append(("verdict",))
    p._rebuild_ranking_rows = lambda: p.calls.append(("rebuild",))
    p._refresh_header = lambda: p.calls.append(("header",))
    p._set_header_message = lambda msg: p.calls.append(("msg", msg))
    p._update_cum_labels = lambda: p.calls.append(("cum",))
    p._start_pending_load = lambda: p.calls.append(("pending_load",))   # Pending 조회 시작 (스레드 없이 기록만)
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


# ── Sort by 전환: 1열 상태 + 2열 탭 + 3열 판정 제목·갱신 순서 ─────────────
@pytest.mark.parametrize("state", ["ANALYSIS", "RANKING"])
@pytest.mark.parametrize("mode", _MODES)
def test_select_sort_cross_column_sequence(mode, state):
    title = _Lbl()
    btn = _Lbl()
    popup = _Popup()
    p = _panel(_sort_mode="24h Ticker", _sort_btn=btn, _verdict_title_lbl=title,
               _hdr_labels=[_Lbl() for _ in range(6)], _app_state=state, _time_fixed=False)
    p._select_sort(mode, popup)

    tab = {"4TF Optimization": "macro", "Sharp rise": "mtf", "Sharp decline": "mtf"}.get(mode, "chart")
    # 3열 판정 다시 그리기는 분석 중(종목 선택 상태)일 때만 (2026-11-12 B-2)
    expected = [("tab", tab)] + ([("verdict",)] if state == "ANALYSIS" else []) + [("rebuild",)]
    if mode == "Pending Listing":
        # P2: '로드 중'으로 먼저 바꾼 뒤(조회 시작) 재빌드 — 기존 after(0) 예약은 옛 목록을 먼저 그렸음
        expected.insert(0, ("pending_load",))
    assert p.calls == expected
    assert popup.destroyed
    assert p._sort_mode == mode
    assert btn.cfg["text"] == f"  {mode}  ▼"
    assert title.cfg["text"] == f"📋 {mode} 분석 및 권장 레버리지"


def test_select_sort_without_title_label_still_refreshes():
    p = _panel(_sort_mode="24h Ticker", _sort_btn=None, _verdict_title_lbl=None,
               _hdr_labels=[_Lbl() for _ in range(6)], _app_state="ANALYSIS", _time_fixed=False)
    p._select_sort("Volatility", _Popup())
    assert p.calls == [("tab", "chart"), ("verdict",), ("rebuild",)]


# ── Time Fix 타이머: 30초마다 ANALYSIS 선택 심볼 상세 갱신 요청 ────────────
def _timer_panel(elapsed, state="ANALYSIS", sym="XUSDT", running=True):
    return _panel(_timer_running=running, _time_fixed=running, _elapsed_sec=elapsed,
                  _timer_lbl=None, _app_state=state, _sel_var=_Var(sym))


@pytest.fixture()
def dm(monkeypatch):
    d = _DM()
    monkeypatch.setattr(_ctx, "_data_mgr", d)
    return d


def test_tick_requests_detail_every_30s_in_analysis(dm):
    p = _timer_panel(29)
    p._tick_timer()
    assert dm.requested == ["XUSDT"]
    assert p._elapsed_sec == 30
    assert p.calls == [("cum",), ("after", 1000, "_tick_timer")]


@pytest.mark.parametrize("elapsed,state,sym", [
    (28, "ANALYSIS", "XUSDT"),   # 30초 경계 아님
    (29, "RANKING",  "XUSDT"),   # ANALYSIS 아님
    (29, "IDLE",     "XUSDT"),
    (29, "ANALYSIS", ""),        # 선택 심볼 없음
])
def test_tick_no_detail_request(dm, elapsed, state, sym):
    p = _timer_panel(elapsed, state, sym)
    p._tick_timer()
    assert dm.requested == []
    assert p.calls == [("cum",), ("after", 1000, "_tick_timer")]


def test_tick_without_data_manager(monkeypatch):
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    p = _timer_panel(29)
    p._tick_timer()
    assert p.calls == [("cum",), ("after", 1000, "_tick_timer")]


def test_tick_reschedules_even_if_request_fails(monkeypatch):
    monkeypatch.setattr(_ctx, "_data_mgr", _DM(fail=True))
    p = _timer_panel(29)
    p._tick_timer()
    assert p.calls[-1] == ("after", 1000, "_tick_timer")


def test_tick_stops_when_not_running(dm):
    p = _timer_panel(29, running=False)
    p._tick_timer()
    assert p.calls == [] and dm.requested == []


# ── Assign: 3열 버튼 → 공유 심볼(하단 엔진) ────────────────────────────
@pytest.fixture()
def assign_ctx(monkeypatch):
    monkeypatch.setattr(_ctx, "_data_mgr", _DM())
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL({"BADUSDT"}))


def test_assign_then_toggle_off(assign_ctx):
    shared = _Var("")
    p = _panel(_assigned_sym=None, _shared_sym=shared)
    p._on_assign("AUSDT")
    assert (p._assigned_sym, shared.get()) == ("AUSDT", "AUSDT")
    p._on_assign("AUSDT")
    assert (p._assigned_sym, shared.get()) == (None, "")
    assert p.calls == [("header",), ("header",)]


def test_assign_blacklisted_blocked(assign_ctx):
    shared = _Var("")
    p = _panel(_assigned_sym=None, _shared_sym=shared)
    p._on_assign("BADUSDT")
    assert (p._assigned_sym, shared.get()) == (None, "")
    assert p.calls == [("msg", "⛔ BADUSDT — 블랙리스트 등록 심볼이므로 배정할 수 없습니다")]


def test_shared_sym_external_change_syncs_assign():
    shared = _Var("")
    p = _panel(_assigned_sym="AUSDT", _shared_sym=shared)
    p._on_shared_sym_changed()                 # 하단 [Clear] → ""
    assert p._assigned_sym is None
    shared.set("BUSDT")                        # 하단에서 다른 심볼로 되돌림
    p._on_shared_sym_changed()
    assert p._assigned_sym == "BUSDT"
    p._on_shared_sym_changed()                 # 변화 없음 → 헤더 재갱신 없음
    assert p.calls == [("header",), ("header",)]


# ── 4TF Optimization 종합분석 판정 렌더링 (FourTFScorer 점수 키만 사용) ─────
def _row(sym):
    return (sym, 100, "─ 로딩중", "#888888", "  +1.00%", "#00ff00", "+1.00%", "#00ff00",
            "⟳ 전환 대기", "#ffff00", 4)


def test_refresh_verdict_4tf_renders(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        ind = {"tf1h": {"dir": "▲"}, "tf1": {"dir": "▲", "k": 10.0}, "tf3": {"dir": "▲"},
               "tf5": {"dir": "▲"}, "tf15": {"dir": "▼"}, "tf4h": {"dir": "▲"},
               "tf1d": {"dir": "▼"}, "atr": 4.0, "funding_rate": 0.01, "oi_change": 2.0,
               "oi_change_1h": 5.0, "long_ratio": 65.0}
        monkeypatch.setattr(_ctx, "_data_mgr", _DM({"AUSDT": ind}, [_row("AUSDT")]))
        monkeypatch.setattr(_ctx, "_bl_mgr", _BL())
        p = MiddlePanel.__new__(MiddlePanel)
        p._verdict_f = tk.Frame(root)
        p._sel_var = _Var("AUSDT")
        p._sort_mode = "4TF Optimization"
        p._refresh_verdict()
        texts = [w.cget("text") for f in p._verdict_f.winfo_children()
                 for w in f.winfo_children() if isinstance(w, tk.Label)]
        # 10점 만점 (FR·ATR 제거): 단기일치 3 + 1m진입 1 + 일일강도 1 + 거래량Top10 1(1위) + OI 1h 1 + 추세쏠림 1 = 8
        assert "전체 1위 · 총 8/10점" in texts
        # 일일 추세 1h▲·4h▲·1d▼ → ▲ 2/3 (일일강도 1), 단기 1m▲·3m▲·5m▲·15m▼ → ▲ 3/4 (단기일치 3)
        assert any("단기일치 3/4(+3)" in t and "일일강도 1/2(+1)" in t for t in texts)
        direct = [w.cget("text") for w in p._verdict_f.winfo_children() if isinstance(w, tk.Label)]
        assert "일일 추세 ▲ 2/3  ·  단기 추세 ▲ 3/4" in direct
        assert not any("일일 추세 중립" in t for t in direct)
        assert not any("세션일치" in t for t in texts)
    finally:
        root.destroy()
