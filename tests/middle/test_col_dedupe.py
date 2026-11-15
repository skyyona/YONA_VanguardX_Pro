"""
tests/middle/test_col_dedupe.py
1열 정리 3단계(중복 통합) — 행 배경 단일 정의, Gold(Player 맵 재사용·블랙리스트 제외),
3열 Player 표시(태그 문구·방향 단일 출처, 복수 플레이어 메시지 공용 키, 파생 판정 줄 = 에너지 패널 태그).
"""
import threading
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.analysis.tag_detector import TagDetector, _TAG_META, _make_tag
from middle.col1_ranking.ranking.gold_ranking import GoldRanking
from middle.data.data_manager import MiddleDataManager
from middle.analysis.forecast import Forecaster
from middle.widget.constants import (
    DARK_ROW_EVN, DARK_ROW_ODD, GOLD_ROW_BG, LIGHT_GREEN, NEGATIVE, ORANGE, PLAYER_MIX_ROW_BG,
    PLAYER_ROW_BG, PLAYER_SHORT_ROW_BG, POSITIVE,
)
from middle.widget.middle_panel import MiddlePanel

_BASE = {"long_ratio": 50.0, "funding_rate": 0.0, "oi_change": 0.0, "vss": 1.0,
         "bpr": 0.5, "atr": 2.0, "price_change_pct": 0.0}
# VSS 3.0·BPR 0.2·FR 0.12% → 고래 매도 + FR+ 과열 (하락 태그 2개, 구 키워드 목록엔 "FR+"만 해당)
_WSELL_FRP = dict(_BASE, vss=3.0, bpr=0.2, funding_rate=0.12)
# 롱 81%·ATR 3.5% → 청산 헌터 단독
_HUNTER = dict(_BASE, long_ratio=81.0, atr=3.5)


def _row(sym):
    return (sym, 9999, "─ 로딩중", "#888888", "  +1.00%", "#00ff00", "+1.00%", "#00ff00",
            "⟳ 전환 대기", "#ffff00", 4)


class _BL:
    def __init__(self, syms=()):
        self.syms = set(syms)

    def is_blacklisted(self, sym):
        return sym in self.syms

    def get_all(self):
        return self.syms


def _dm(monkeypatch, ind: dict) -> MiddleDataManager:
    m = MiddleDataManager.__new__(MiddleDataManager)
    m._ind_cache = {s: dict(v) for s, v in ind.items()}
    m._tkr_map, m._onboard_map = {}, {}
    m._ranking_rows = [_row(s) for s in ind]
    m._vol_rank = {s: i + 1 for i, s in enumerate(ind)}   # 갱신 대상(거래량 상위 100) — 지표 사용 (_ind_fresh)
    m._engine_sym = m._last_detail_sym = ""
    m._lock, m._forecast, m._forecaster = threading.Lock(), {}, Forecaster(None)   # 가격 예고 — 판정식 없음
    monkeypatch.setattr(_ctx, "_data_mgr", m)
    return m


@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    r.withdraw()
    yield r
    r.destroy()


def _labels(frame):
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label):
                out.append((c.cget("text"), c.cget("fg")))
            walk(c)
    walk(frame)
    return out


# ── A: 행 배경 단일 정의 — 재구성·선택 복원·_on_select 모두 같은 결과 ─────────
def _bg_panel(root):
    p = MiddlePanel.__new__(MiddlePanel)
    p._gold_sym = "GUSDT"
    p._player_tags_map = {"SUSDT": {"direction": "short"}, "MUSDT": {"direction": "mixed"},
                          "LUSDT": {"direction": "long"}, "GUSDT": {"direction": "short"}}
    p._special, p._sel_idx, p._sel_var = {}, -1, tk.StringVar(root, "")
    syms = ["GUSDT", "SUSDT", "MUSDT", "LUSDT", "AUSDT", "BUSDT"]
    p._row_frames = [(tk.Frame(root), s) for s in syms]
    return p, syms


_EXPECTED_BG = [GOLD_ROW_BG, PLAYER_SHORT_ROW_BG, PLAYER_MIX_ROW_BG, PLAYER_ROW_BG, DARK_ROW_ODD, DARK_ROW_EVN]


def test_row_bg_priority(root):
    p, syms = _bg_panel(root)
    assert [p._row_bg(s, i) for i, s in enumerate(syms)] == _EXPECTED_BG


def test_restore_and_select_use_same_row_bg(root):
    from middle.widget.constants import DARK_SEL
    p, syms = _bg_panel(root)
    p._restore_row_highlight(5)
    assert [f.cget("bg") for f, _ in p._row_frames] == _EXPECTED_BG[:5] + [DARK_SEL]
    p._app_state, p._sort_mode = "RANKING", "Pending Listing"     # 배경 변경 후 즉시 반환 경로
    p._on_select("AUSDT", 4)
    assert [f.cget("bg") for f, _ in p._row_frames] == _EXPECTED_BG[:4] + [DARK_SEL, _EXPECTED_BG[5]]


# ── B·F: Gold — Player 맵 재사용(같은 결과), 블랙리스트 제외 ─────────────────
def test_gold_player_map_same_result_without_redetect(monkeypatch):
    dm = _dm(monkeypatch, {"HUSDT": _HUNTER, "WUSDT": _WSELL_FRP, "NUSDT": _BASE})
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL())
    pm = dm.get_player_map()
    expected = {s: GoldRanking.calc(s) for s in dm._ind_cache}
    calls = []
    orig = MiddleDataManager.get_player
    monkeypatch.setattr(MiddleDataManager, "get_player", lambda self, s: (calls.append(s), orig(self, s))[1])
    assert {s: GoldRanking.calc(s, pm) for s in dm._ind_cache} == expected
    assert GoldRanking.get_top1(pm) == GoldRanking.get_top1()
    calls.clear()
    GoldRanking.get_top1(pm)
    assert calls == []                      # 맵 전달 시 심볼별 Player 재감지 없음


def test_gold_excludes_blacklisted(monkeypatch):
    dm = _dm(monkeypatch, {"HUSDT": _HUNTER, "WUSDT": _WSELL_FRP, "NUSDT": _BASE})
    scores = {s: GoldRanking.calc(s) for s in dm._ind_cache}
    top, second = sorted(scores, key=lambda s: -scores[s])[:2]
    assert scores[top] > scores[second]
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL())
    assert GoldRanking.get_top1() == top
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL({top}))
    assert GoldRanking.get_top1() == second


# ── C: 3열 태그 문구·방향 — TagDetector 단일 출처, 기존 표시 유지 ──────────────
@pytest.mark.parametrize("key,expected", [
    ("세력 매집", ("롱 우세", POSITIVE)), ("고래 매수", ("롱 우세", POSITIVE)),
    ("기관 유입", ("롱 우세", POSITIVE)), ("FR-", ("롱 우세", LIGHT_GREEN)),
    ("세력 분산", ("숏 우세", NEGATIVE)), ("고래 매도", ("숏 우세", NEGATIVE)),
    ("롱 스퀴즈", ("숏 우세", NEGATIVE)), ("청산 헌터", ("숏 우세", NEGATIVE)),
    ("FOMO 극단", ("주의", ORANGE)), ("FR+ 과열", ("주의", ORANGE)),
])
def test_player_direction_all_tags(key, expected):
    assert MiddlePanel._player_direction(_make_tag(key, 50)) == expected


def test_all_tag_keys_classified():
    assert set(_TAG_META) == TagDetector.RISE_KEYS | TagDetector.DECLINE_KEYS


# ── D: 복수 플레이어 메시지 — 공용 하락 키(고래 매도 포함) ───────────────────
def test_energy_combined_msg_counts_whale_sell(monkeypatch, root):
    _dm(monkeypatch, {"WUSDT": _WSELL_FRP})
    p = MiddlePanel.__new__(MiddlePanel)
    p._energy_f, p._sel_var, p._sort_mode = tk.Frame(root), tk.StringVar(root, "WUSDT"), "24h Ticker"
    p._refresh_energy()
    texts = [t for t, _ in _labels(p._energy_f)]
    assert "🐋 고래 매도" in texts and "💰 FR+ 과열" in texts
    assert "대형 단일 체결 — 즉각적 매도 압력 발생" in texts       # 문구 = TagDetector 단일 정의
    assert "  숏 우세" in texts and "  주의" in texts
    assert "복수 하락 플레이어 동시 활동\n→ 숏 에너지 복합 확인 — 숏 엔진 진입 권장" in texts


# ── E: 종합분석 파생 판정 줄 — 에너지 패널과 같은 Player 판정 ──────────────────
def test_verdict_derivative_line_uses_shared_player(monkeypatch, root):
    _dm(monkeypatch, {"WUSDT": dict(_WSELL_FRP, _player_tags=[("🎯 청산 헌터", "#f00", 80)])})
    monkeypatch.setattr(_ctx, "_bl_mgr", _BL())
    p = MiddlePanel.__new__(MiddlePanel)
    p._verdict_f, p._sel_var, p._sort_mode = tk.Frame(root), tk.StringVar(root, "WUSDT"), "Volatility"
    p._refresh_verdict()
    line = [t for t, _ in _labels(p._verdict_f) if t.startswith("OI ")]
    assert line == ["OI +0.0%·💰 FR+·🐋 고래"]            # 강도순 · 상세 갱신 저장값(청산 헌터) 아님
