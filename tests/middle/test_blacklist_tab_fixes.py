"""
tests/middle/test_blacklist_tab_fixes.py
1열 2탭 Blacklist 결함 수정 (2026-11-18)
 B-1  Settling 안내 행("Settling 조회 중..."·"Settling 조회 실패 …"·"감지된 심볼 없음")은 체크·등록되지 않음
      — 판정: 데이터 행은 순번 칸이 str(idx+1), 안내 행은 빈 문자열 (Settling·Blacklist 공용 체크 핸들러)
 UI-2 Add·Release는 ☑ 체크된 심볼만 처리 — 체크가 없으면 포커스 행이 있어도 아무것도 하지 않음
 ②   엔진 배정 종목은 블랙리스트에 등록하지 않음 (2026-11-22 — 엔진이 블랙리스트 종목을 갖는 경로 차단)
 1번 3열 분석 중 종목 직접 등록 — 확인 창 → MANUAL 등록 → 분석 자동 종료('가') (2026-11-22)
 2·3번 5분 캐시 exchangeInfo로 Settling 자동 감지(새 조회 없음)·거래 재개 자동 해제(MANUAL 제외) (2026-11-22)
 ⑤   1열 목록이 바뀔 때만 Time Fix 해제·재생성 · ① 0.00% 표시 · ② Settling 조회 실패 로그 (2026-11-22)
 N-1 5분 자동 감지가 탭보다 먼저 돌아도 탭 첫 표시에 목록이 그려짐 · N-2 체크 없이 Add·Release 시 안내 (2026-11-22)
블랙리스트 파일은 tmp_path 임시 경로만 사용 (실제 middle/data/_blacklist.json 미사용).
체크 칸 클릭은 Treeview 위치 판별(identify_region·identify_column·identify_row)을 대역으로 바꿔 시험한다
(숨긴 테스트 창은 셀 좌표가 없음 — 실제 클릭 확인은 별도 실행으로 수행).
"""
import tkinter as tk
import tkinter.ttk as ttk
import types

import pytest

import middle.widget.panel_col1_blacklist as _blmod
import middle.widget.shared_context as _ctx
from middle.data.blacklist import BlacklistManager
from middle.data.settling import SettlingEntry
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


@pytest.fixture()
def bl(monkeypatch, tmp_path):
    p = tmp_path / "_blacklist.json"
    p.write_text("[]", encoding="utf-8")
    m = BlacklistManager(p)
    monkeypatch.setattr(_ctx, "_bl_mgr", m)
    monkeypatch.setattr(_ctx, "_data_mgr", None)
    return m


_ENTRIES = [SettlingEntry("AAAUSDT", "BREAK", "HALT", "halt"),
            SettlingEntry("BBBUSDT", "SETTLING", "SETTLING", "settling")]


def _panel(root, cache, status="ok"):
    p = MiddlePanel.__new__(MiddlePanel)
    p._t_tree = ttk.Treeview(root, columns=("rank", "check", "symbol", "change", "status"), show="headings")
    p._b_tree = ttk.Treeview(root, columns=("rank", "check", "symbol", "change", "added", "status"), show="headings")
    p._checked_settling, p._checked_blacklist = set(), set()
    p._settling_cache, p._settling_status = list(cache), status
    p._row_frames = []                       # 1열 표시 행 (MiddlePanel.__init__ 기본값)
    p.msgs = []
    p._set_header_message = p.msgs.append    # 3열 헤더 안내 (실앱: MiddlePanel._set_header_message)
    p.calls = []
    p._release_time_fix_for_rebuild = lambda: p.calls.append("timefix")
    p._rebuild_ranking_rows = lambda: p.calls.append("rebuild")
    p._render_settling_tree(p._t_tree)
    p._refresh_blacklist_ui()
    return p


def _click_check(p, tree, row, checked):
    """체크 칸(#2) 클릭 — 위치 판별만 대역, 토글 로직은 실제 코드."""
    tree.identify_region = lambda x, y: "cell"
    tree.identify_column = lambda x: "#2"
    tree.identify_row = lambda y: row
    p._toggle_tree_check(types.SimpleNamespace(x=0, y=0), tree, checked, 2)


@pytest.mark.parametrize("status, msg", [("ok", "감지된 심볼 없음"),
                                         ("loading", "Settling 조회 중..."),
                                         ("failed", "Settling 조회 실패 — 앱 재시작 시 다시 조회")])
def test_b1_guide_row_not_checked_or_added(root, bl, status, msg):
    p = _panel(root, [], status)
    row = p._t_tree.get_children()[0]
    assert p._t_tree.item(row, "values")[2] == msg
    _click_check(p, p._t_tree, row, p._checked_settling)          # 경로 B: 체크 칸 클릭
    assert p._checked_settling == set() and p._t_tree.item(row, "values")[1] == ""
    p._t_tree.focus(row)                                            # 경로 A: 행 포커스
    p._add_to_blacklist()
    assert bl.get_all() == [] and p.calls == []                    # 등록·재생성 없음


def test_b1_guide_text_in_checked_set_is_ignored(root, bl):
    p = _panel(root, [])
    p._checked_settling.add("감지된 심볼 없음")                     # 체크 집합에 들어와도 추가 경로가 안내 행을 거름
    p._add_to_blacklist()
    assert bl.get_all() == []


def test_ui2_no_check_does_nothing_even_with_focus(root, bl):
    p = _panel(root, _ENTRIES)
    p._t_tree.focus(p._t_tree.get_children()[0])                   # 수정 전: 체크 없으면 포커스 행(AAAUSDT) 추가
    p._add_to_blacklist()
    assert bl.get_all() == [] and p.calls == []
    bl.add("ZZZUSDT", status="HALT")
    p._refresh_blacklist_ui()
    p._b_tree.focus(p._b_tree.get_children()[0])                   # 수정 전: 체크 없으면 포커스 행 해제
    p._release_from_blacklist()
    assert bl.is_blacklisted("ZZZUSDT") and p.calls == []


def test_ui2_check_then_uncheck_adds_nothing(root, bl):
    p = _panel(root, _ENTRIES)
    row = p._t_tree.get_children()[0]
    _click_check(p, p._t_tree, row, p._checked_settling)
    _click_check(p, p._t_tree, row, p._checked_settling)           # ☑ → ☐
    p._t_tree.focus(row)                                            # 체크 칸 클릭이 남기는 포커스
    p._add_to_blacklist()
    assert bl.get_all() == []


def test_checked_rows_added_with_label_status(root, bl):
    """회귀 — 체크된 실제 행은 표시 상태(label)로 등록, Settling 목록에서 빠지고 1열 재생성."""
    p = _panel(root, _ENTRIES)
    for row in p._t_tree.get_children():
        _click_check(p, p._t_tree, row, p._checked_settling)
    p._add_to_blacklist()
    assert {(e.symbol, e.status) for e in bl.get_all()} == {("AAAUSDT", "HALT"), ("BBBUSDT", "SETTLING")}
    assert [p._t_tree.item(r, "values")[2] for r in p._t_tree.get_children()] == ["감지된 심볼 없음"]
    assert p.calls == []                     # ⑤ Settling 종목은 1열에 없음 — Time Fix 유지·재생성 없음


def test_blacklist_tree_check_and_release(root, bl):
    """회귀 — 공용 체크 핸들러: Blacklist 트리 실제 행 체크·해제 정상."""
    bl.add("ZZZUSDT", status="HALT")
    p = _panel(root, [])
    row = p._b_tree.get_children()[0]
    _click_check(p, p._b_tree, row, p._checked_blacklist)
    assert p._checked_blacklist == {"ZZZUSDT"} and p._b_tree.item(row, "values")[1] == "☑"
    p._release_from_blacklist()
    assert not bl.is_blacklisted("ZZZUSDT") and p.calls == []   # ⑤ 거래 중 아님(시세 없음) — 1열 변화 없음


def test_assigned_symbol_excluded_others_added(root, bl):
    """② 배정 종목(AAAUSDT)과 다른 종목을 함께 체크 → 배정 종목만 제외·안내, 나머지는 등록."""
    p = _panel(root, _ENTRIES)
    p._assigned_sym = "AAAUSDT"
    msgs = []
    p._set_header_message = msgs.append
    for row in p._t_tree.get_children():
        _click_check(p, p._t_tree, row, p._checked_settling)
    p._add_to_blacklist()
    assert [e.symbol for e in bl.get_all()] == ["BBBUSDT"]
    assert msgs == ["⛔ AAAUSDT — 엔진 배정 종목은 블랙리스트에 등록할 수 없습니다 (배정 해제 후 등록)"]
    assert p.calls == []                     # ⑤ BBBUSDT는 1열에 없음


def test_only_assigned_symbol_checked_adds_nothing(root, bl):
    """② 배정 종목만 체크 → 등록 없음·안내만 (1열 재생성 없음)."""
    p = _panel(root, _ENTRIES)
    p._assigned_sym = "AAAUSDT"
    msgs = []
    p._set_header_message = msgs.append
    _click_check(p, p._t_tree, p._t_tree.get_children()[0], p._checked_settling)
    p._add_to_blacklist()
    assert bl.get_all() == [] and len(msgs) == 1 and p.calls == []


# ── 1번: 3열 분석 중 종목 직접 등록 ────────────────────────────
def _direct_panel(root, monkeypatch, answer, state="ANALYSIS", assigned=None):
    p = _panel(root, [])
    p._app_state, p._assigned_sym = state, assigned
    p.msgs, p.asked = [], []
    p._set_header_message = p.msgs.append
    p.on_clear_analysis = lambda: p.calls.append("clear")

    def _ask(title, text, parent=None):
        p.asked.append(title)
        return answer
    monkeypatch.setattr(_blmod.messagebox, "askyesno", _ask)
    return p


def test_direct_register_yes_in_analysis_clears(root, bl, monkeypatch):
    p = _direct_panel(root, monkeypatch, True)
    p._blacklist_selected_symbol("XYZUSDT")
    (e,) = bl.get_all()
    assert (e.symbol, e.status, e.reason) == ("XYZUSDT", "MANUAL", "사용자 직접 등록")
    assert p.asked == ["블랙리스트 등록"] and p.calls == ["clear"]                     # '가': 분석 자동 종료
    assert [p._b_tree.item(r, "values")[2] for r in p._b_tree.get_children()] == ["XYZUSDT"]


def test_direct_register_no_does_nothing(root, bl, monkeypatch):
    p = _direct_panel(root, monkeypatch, False)
    p._blacklist_selected_symbol("XYZUSDT")
    assert bl.get_all() == [] and p.calls == [] and p.asked == ["블랙리스트 등록"]


def test_direct_register_assigned_or_already_listed_no_dialog(root, bl, monkeypatch):
    p = _direct_panel(root, monkeypatch, True, assigned="XYZUSDT")
    p._blacklist_selected_symbol("XYZUSDT")                                         # ② 배정 종목
    assert bl.get_all() == [] and p.asked == [] and "엔진 배정 종목" in p.msgs[0]
    bl.add("ABCUSDT", status="SETTLING")
    p._blacklist_selected_symbol("ABCUSDT")                                         # 이미 등록 — 상태 덮어쓰지 않음
    assert bl.get_all()[0].status == "SETTLING" and p.asked == [] and "이미" in p.msgs[1]


def test_direct_register_in_ranking_rebuilds(root, bl, monkeypatch):
    p = _direct_panel(root, monkeypatch, True, state="RANKING")
    p._row_frames = [(None, "XYZUSDT")]      # 1열에 표시된 종목
    p._blacklist_selected_symbol("XYZUSDT")
    assert bl.is_blacklisted("XYZUSDT") and p.calls == ["timefix", "rebuild"]


def test_col3_header_has_blacklist_button(root, bl, monkeypatch):
    """3열 액션 바에 Assign 옆 '⛔ Blacklist' 버튼 — 같은 표식(_is_assign_btn)으로 함께 생성·제거, 누르면 등록 처리 호출."""
    p = MiddlePanel.__new__(MiddlePanel)
    p._hdr_f, p._action_bar = tk.Frame(root), tk.Frame(root)
    p._sel_var = tk.StringVar(root, value="XYZUSDT")
    p._assigned_sym = None
    called = []
    p._blacklist_selected_symbol = called.append
    p._refresh_header()
    btns = {w.cget("text"): w for w in p._action_bar.winfo_children()}
    assert set(btns) == {"  Assign Symbol  ", "⛔  Blacklist"}
    assert all(getattr(w, "_is_assign_btn", False) for w in btns.values())
    btns["⛔  Blacklist"].invoke()
    assert called == ["XYZUSDT"]


# ── 2·3번: Settling 자동 감지 · 거래 재개 자동 해제 ──────────────
class _CacheDM:
    """5분 캐시 exchangeInfo만 공급 — 새 조회(fetch_exchange_info)는 호출 횟수만 기록."""

    def __init__(self, info, trading=()):
        self.info, self.fetches, self.trading = info, 0, set(trading)

    def cached_exchange_info(self):
        return self.info

    def fetch_exchange_info(self):
        self.fetches += 1
        return None

    def get_ticker(self, sym):
        if sym in self.trading:              # 거래 중 심볼만 시세 있음 (1열 목록과 같은 기준)
            from middle.models import SymbolTicker
            return SymbolTicker(sym, 1.0, 0.0, 1.5, 1.0, 1.0, 1.0)
        return None


def _ei(**status):
    return {"symbols": [{"symbol": s, "status": st} for s, st in status.items()]}


def _auto_panel(root, monkeypatch, info, trading=()):
    dm = _CacheDM(info, trading)
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    p = _panel(root, [])
    p.scheduled = []
    p.after = lambda ms, fn: p.scheduled.append(ms)
    return p, dm


def test_auto_refresh_uses_cache_and_reschedules(root, bl, monkeypatch):
    p, dm = _auto_panel(root, monkeypatch, _ei(XXXUSDT="SETTLING", YYYUSDT="BREAK", ZZZUSDT="TRADING"))
    p._auto_settling_refresh()
    rows = [p._t_tree.item(r, "values") for r in p._t_tree.get_children()]
    assert [(v[2], v[4]) for v in rows] == [("XXXUSDT", "SETTLING"), ("YYYUSDT", "HALT")]
    assert dm.fetches == 0 and p.scheduled == [300_000]                     # 새 조회 없음 · 5분 뒤 다시 예약


def test_tab_open_uses_cache_without_fetch(root, bl, monkeypatch):
    p, dm = _auto_panel(root, monkeypatch, _ei(XXXUSDT="SETTLING"))
    p._settling_cache, p._settling_status = [], "loading"
    p._load_settling_data()
    assert dm.fetches == 0 and p._settling_status == "ok"
    assert [p._t_tree.item(r, "values")[2] for r in p._t_tree.get_children()] == ["XXXUSDT"]


def test_auto_release_resumed_symbols_except_manual(root, bl, monkeypatch):
    for sym, st in (("AAAUSDT", "SETTLING"), ("BBBUSDT", "MANUAL"), ("CCCUSDT", "HALT"), ("DDDUSDT", "DELISTED")):
        bl.add(sym, status=st)
    p, _ = _auto_panel(root, monkeypatch, _ei(AAAUSDT="TRADING", BBBUSDT="TRADING", CCCUSDT="BREAK"),   # DDD 거래소에 없음
                       trading={"AAAUSDT", "BBBUSDT"})
    p._refresh_blacklist_ui()
    p._auto_settling_refresh()
    assert sorted(e.symbol for e in bl.get_all()) == ["BBBUSDT", "CCCUSDT", "DDDUSDT"]   # 거래 재개 AAA만 해제
    assert p.calls == ["timefix", "rebuild"]                                            # 1열 복귀
    assert sorted(p._b_tree.item(r, "values")[2] for r in p._b_tree.get_children()) == ["BBBUSDT", "CCCUSDT", "DDDUSDT"]


def test_auto_refresh_keeps_checks_and_skips_unchanged(root, bl, monkeypatch):
    p, dm = _auto_panel(root, monkeypatch, _ei(XXXUSDT="SETTLING", YYYUSDT="SETTLING"))
    p._auto_settling_refresh()
    _click_check(p, p._t_tree, p._t_tree.get_children()[0], p._checked_settling)       # XXX 체크
    before = p._t_tree.get_children()
    p._auto_settling_refresh()                                                          # 변화 없음 — 다시 그리지 않음
    assert p._t_tree.get_children() == before and p._checked_settling == {"XXXUSDT"}
    dm.info = _ei(XXXUSDT="SETTLING", YYYUSDT="SETTLING", WWWUSDT="BREAK")              # 새 감지 종목
    p._auto_settling_refresh()
    vals = {p._t_tree.item(r, "values")[2]: p._t_tree.item(r, "values")[1] for r in p._t_tree.get_children()}
    assert vals == {"WWWUSDT": "☐", "XXXUSDT": "☑", "YYYUSDT": "☐"} and p._checked_settling == {"XXXUSDT"}


def test_client_keeps_last_exchange_info():
    """5분 캐시가 성공한 exchangeInfo 원본을 보관 — 실패 시 이전 보관본 유지 (새 조회 없는 재사용용)."""
    from middle.api.binance_client import MiddleBinanceClient
    c = MiddleBinanceClient.__new__(MiddleBinanceClient)
    c._trading_symbols, c._trading_cache_ts, c._trading_fail_ts, c._exchange_info = set(), 0.0, 0.0, None
    ok = _ei(AAAUSDT="TRADING", BBBUSDT="SETTLING")
    c.fetch_exchange_info = lambda: ok
    assert c._get_trading_symbols() == {"AAAUSDT"} and c.cached_exchange_info() is ok
    c._trading_cache_ts = 0.0                                                           # 캐시 만료
    c.fetch_exchange_info = lambda: None                                                # 조회 실패
    c._get_trading_symbols()
    assert c.cached_exchange_info() is ok


# ── 경미 ⑤·①·② ───────────────────────────────────────────────
def test_release_trading_symbol_rebuilds(root, bl, monkeypatch):
    """⑤ 거래 중(시세 있음) 종목 해제 → 1열에 다시 나올 수 있으므로 Time Fix 해제·재생성."""
    bl.add("TTTUSDT", status="MANUAL")
    p, _ = _auto_panel(root, monkeypatch, None, trading={"TTTUSDT"})
    p._refresh_blacklist_ui()
    _click_check(p, p._b_tree, p._b_tree.get_children()[0], p._checked_blacklist)
    p._release_from_blacklist()
    assert not bl.is_blacklisted("TTTUSDT") and p.calls == ["timefix", "rebuild"]


def test_add_shown_symbol_rebuilds(root, bl):
    """⑤ 1열에 표시된 종목을 Settling에서 등록 → 즉시 제외되도록 재생성."""
    p = _panel(root, _ENTRIES)
    p._row_frames = [(None, "AAAUSDT")]
    _click_check(p, p._t_tree, p._t_tree.get_children()[0], p._checked_settling)
    p._add_to_blacklist()
    assert bl.is_blacklisted("AAAUSDT") and p.calls == ["timefix", "rebuild"]


def test_change_zero_percent_shown(monkeypatch, bl):
    """① 실제 0.00%는 '+0.00%' (기존: 시세 없음 '—'로 표시) · 시세 없으면 '—'."""
    from middle.models import SymbolTicker

    class _DM:
        def get_ticker(self, sym):
            return SymbolTicker(sym, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0) if sym == "ZEROUSDT" else None
    monkeypatch.setattr(_ctx, "_data_mgr", _DM())
    p = MiddlePanel.__new__(MiddlePanel)
    assert p._get_change_str("ZEROUSDT")[0] == "+0.00%"
    assert p._get_change_str("NONEUSDT")[0] == "—"


def test_settling_fetch_failure_logged(root, bl, monkeypatch, caplog):
    """② Settling 조회 예외 원인을 로그에 남김 (기존: 조용히 무시)."""
    import logging
    import threading

    class _FailDM:
        def cached_exchange_info(self):
            return None

        def fetch_exchange_info(self):
            raise RuntimeError("연결 실패")
    monkeypatch.setattr(_ctx, "_data_mgr", _FailDM())
    p = _panel(root, [], "loading")
    done = threading.Event()
    p._post = lambda fn, *a: done.set()
    with caplog.at_level(logging.WARNING):
        p._load_settling_data()
        assert done.wait(5)
    assert "Blacklist Settling 조회 실패: 연결 실패" in caplog.text


# ── N-1 · N-2 ─────────────────────────────────────────────────
def test_tab_open_after_auto_refresh_renders(root, bl, monkeypatch):
    """N-1 — 탭을 열기 전에 5분 자동 감지가 먼저 돌아도 탭 첫 표시에 목록이 그려진다 (실앱 순서 그대로, 상태 되돌림 없음)."""
    dm = _CacheDM(_ei(XXXUSDT="SETTLING", YYYUSDT="BREAK"))
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    p = MiddlePanel.__new__(MiddlePanel)
    p._checked_settling, p._checked_blacklist, p._row_frames = set(), set(), []
    p._settling_cache, p._settling_status = [], "loading"          # MiddlePanel.__init__ 기본값
    p._release_time_fix_for_rebuild = p._rebuild_ranking_rows = lambda: None
    p.after = lambda ms, fn: None
    p._auto_settling_refresh()                                       # 1) 탭 미생성(_t_tree 없음) 상태로 +5분 자동 감지
    assert getattr(p, "_t_tree", None) is None and p._settling_status == "ok"
    p._t_tree = ttk.Treeview(root, columns=("rank", "check", "symbol", "change", "status"), show="headings")   # 2) 탭 첫 생성
    p._load_settling_data()
    assert [p._t_tree.item(r, "values")[2] for r in p._t_tree.get_children()] == ["XXXUSDT", "YYYUSDT"]   # 3) 그려짐
    assert dm.fetches == 0


def test_no_check_add_release_show_guide(root, bl):
    """N-2 — 체크 없이 Add·Release → 등록·해제 없이 안내 문구 (기존: 무반응)."""
    bl.add("ZZZUSDT", status="HALT")
    p = _panel(root, _ENTRIES)
    p._add_to_blacklist()
    p._release_from_blacklist()
    assert [e.symbol for e in bl.get_all()] == ["ZZZUSDT"] and p.calls == []
    assert p.msgs == ["⛔ 체크한 심볼이 없습니다 — Settling Update 목록의 ☐ 칸을 클릭해 선택한 뒤 Add",
                      "⛔ 체크한 심볼이 없습니다 — Blacklist 목록의 ☐ 칸을 클릭해 선택한 뒤 Release"]
