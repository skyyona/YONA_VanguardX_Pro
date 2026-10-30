"""
tests/bottom_engine/test_blacklist_protection_warning.py
블랙리스트 보호 이상(미로드·파일 오류) 시 경고만 표시 — BlacklistManager.load_error ·
shared_context.blacklist_problem · TradingEngine._warn_blacklist 7건. 엔진 정지·진입 차단 없음.
"""
import threading

import pytest

import bottom_engine.engine_core.trading_engine as _te_mod
import middle.widget.shared_context as _ctx
from bottom_engine.engine_core.trading_engine import EngineState, TradingEngine
from middle.data.blacklist import BlacklistManager

_ENTRY = '{"symbol": "AUSDT", "added_utc": "2026-10-30 00:00 UTC", "status": "MANUAL", "reason": ""}'


@pytest.mark.parametrize("content, loaded, error", [
    (f"[{_ENTRY}]",              1, ""),
    ("[]",                       0, ""),
    (None,                       0, "블랙리스트 파일 없음"),
    ("{broken",                  0, "블랙리스트 파일 파싱 실패"),
    ('{"a": 1}',                 0, "블랙리스트 파일 형식 오류"),
    (f'[{_ENTRY}, {{"bad": 1}}]', 1, "블랙리스트 손상 항목 1건 제외"),
])
def test_load_error_reason(tmp_path, content, loaded, error):
    """로드 결과별 load_error — 정상·빈 목록만 "" (차단 목록 불완전 사유 기록)."""
    path = tmp_path / "_blacklist.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    mgr = BlacklistManager(path)
    assert len(mgr.get_all()) == loaded
    assert mgr.load_error.startswith(error) if error else mgr.load_error == ""


def test_problem_and_engine_warning(tmp_path, monkeypatch):
    """미생성·손상 → 경고 기록(다른 오류는 덮어쓰지 않음), 정상 → 경고 없음."""
    eng = TradingEngine.__new__(TradingEngine)
    eng._lock  = threading.Lock()
    eng._state = EngineState(running=True)
    monkeypatch.setattr(_te_mod, "_blacklist_problem", _ctx.blacklist_problem)

    monkeypatch.setattr(_ctx, "_bl_mgr", None)
    assert _ctx.blacklist_problem() == "블랙리스트 미로드"
    eng._state.error_msg = "[오류] 레버리지 설정 실패"
    eng._warn_blacklist()
    assert eng._state.error_msg == "[오류] 레버리지 설정 실패"
    eng._state.error_msg = ""
    eng._warn_blacklist()
    assert eng._state.error_msg.startswith("[경고] 블랙리스트 미로드")
    assert eng._state.running is True

    path = tmp_path / "_blacklist.json"
    path.write_text(f"[{_ENTRY}]", encoding="utf-8")
    monkeypatch.setattr(_ctx, "_bl_mgr", BlacklistManager(path))
    eng._state.error_msg = ""
    eng._warn_blacklist()
    assert _ctx.blacklist_problem() == ""
    assert eng._state.error_msg == ""
