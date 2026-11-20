"""
tests/middle/test_blacklist_tab_fixes.py
1열 2탭 Blacklist 결함 수정 (2026-11-18)
 B-1  Settling 안내 행("Settling 조회 중..."·"Settling 조회 실패 …"·"감지된 심볼 없음")은 체크·등록되지 않음
      — 판정: 데이터 행은 순번 칸이 str(idx+1), 안내 행은 빈 문자열 (Settling·Blacklist 공용 체크 핸들러)
 UI-2 Add·Release는 ☑ 체크된 심볼만 처리 — 체크가 없으면 포커스 행이 있어도 아무것도 하지 않음
블랙리스트 파일은 tmp_path 임시 경로만 사용 (실제 middle/data/_blacklist.json 미사용).
체크 칸 클릭은 Treeview 위치 판별(identify_region·identify_column·identify_row)을 대역으로 바꿔 시험한다
(숨긴 테스트 창은 셀 좌표가 없음 — 실제 클릭 확인은 별도 실행으로 수행).
"""
import tkinter as tk
import tkinter.ttk as ttk
import types

import pytest

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
    assert p.calls == ["timefix", "rebuild"]


def test_blacklist_tree_check_and_release(root, bl):
    """회귀 — 공용 체크 핸들러: Blacklist 트리 실제 행 체크·해제 정상."""
    bl.add("ZZZUSDT", status="HALT")
    p = _panel(root, [])
    row = p._b_tree.get_children()[0]
    _click_check(p, p._b_tree, row, p._checked_blacklist)
    assert p._checked_blacklist == {"ZZZUSDT"} and p._b_tree.item(row, "values")[1] == "☑"
    p._release_from_blacklist()
    assert not bl.is_blacklisted("ZZZUSDT") and p.calls == ["timefix", "rebuild"]
