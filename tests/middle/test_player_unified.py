"""
tests/middle/test_player_unified.py
Player Detection 단일 정의(MiddleDataManager.get_player·get_player_map) — 1열 행 배경·Sharp rise/decline
Player 가산점(+2)·3열 Player 가산점 표시가 같은 결과를 쓰는지 검증.
- 가산점은 절단 전 전체 태그 기준 (표시용 상위 4개 절단과 무관)
- 랭킹 풀 전 심볼 대상 (상세 갱신 여부와 무관)
"""
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.col1_ranking.ranking.sharp_decline_scorer import SharpDeclineScorer
from middle.col1_ranking.ranking.sharp_rise_scorer import SharpRiseScorer
from middle.data.data_manager import MiddleDataManager
from middle.widget.middle_panel import MiddlePanel

# 롱 86%·FR 0.105%·OI +10.1%·VSS 2.6·BPR 0.66·ATR 5% → 태그 6개:
#   FOMO 극단 100 · FR+ 과열 100 · 롱 스퀴즈 89 · 청산 헌터 75 · 고래 매수 71 · 세력 매집 69
#   상승 태그(고래 매수·세력 매집)가 표시용 상위 4개 밖으로 절단됨
_CUT = {"long_ratio": 86.0, "funding_rate": 0.105, "oi_change": 10.1, "vss": 2.6,
        "bpr": 0.66, "atr": 5.0, "price_change_pct": 1.0}
# 롱 81%·ATR 3.5% → 청산 헌터 단독 (하락 태그)
_HUNTER = {"long_ratio": 81.0, "funding_rate": 0.0, "oi_change": 0.0, "vss": 1.0,
           "bpr": 0.5, "atr": 3.5, "price_change_pct": 0.0}
# VSS 3.0·BPR 0.2 → 고래 매도 단독 (하락 태그)
_WHALE_SELL = {"long_ratio": 50.0, "funding_rate": 0.0, "oi_change": 0.0, "vss": 3.0,
               "bpr": 0.2, "atr": 2.0, "price_change_pct": 0.0}
_NONE = {"long_ratio": 50.0, "funding_rate": 0.0, "oi_change": 0.0, "vss": 1.0,
         "bpr": 0.5, "atr": 2.0, "price_change_pct": 0.0}


def _row(sym):
    """랭킹 11-tuple — 상세 갱신 대상이 아닌 일반 종목."""
    return (sym, 9999, "─ 로딩중", "#888888", "  +1.00%", "#00ff00", "+1.00%", "#00ff00",
            "⟳ 전환 대기", "#ffff00", 4)


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager.__new__(MiddleDataManager)
    m._ind_cache = {"CUTUSDT": dict(_CUT), "HUNTUSDT": dict(_HUNTER),
                    "WSELLUSDT": dict(_WHALE_SELL), "NONEUSDT": dict(_NONE)}
    m._tkr_map, m._onboard_map = {}, {}
    m._ranking_rows = [_row(s) for s in m._ind_cache]
    monkeypatch.setattr(_ctx, "_data_mgr", m)
    return m


def test_detection_full_tags_vs_display_cut(dm):
    det = dm.get_player("CUTUSDT")
    assert [t.tag_key for t in det.tags] == ["FOMO 극단", "FR+ 과열", "롱 스퀴즈", "청산 헌터"]
    assert det.has_rise_tag and det.has_decline_tag      # 절단 전 전체 태그 기준


def test_player_map_background_fields(dm):
    pm = dm.get_player_map()
    assert set(pm) == {"CUTUSDT", "HUNTUSDT", "WSELLUSDT"}          # 태그 없는 종목 제외
    assert pm["CUTUSDT"]["direction"] == "mixed"
    assert pm["HUNTUSDT"]["direction"] == "short"
    assert [t[0] for t in pm["CUTUSDT"]["tags"]] == [t.tag_text for t in dm.get_player("CUTUSDT").tags]


@pytest.mark.parametrize("use_map", [False, True])
def test_sharp_player_bonus_all_symbols_full_tags(dm, use_map):
    pm = dm.get_player_map() if use_map else None
    rise = {s: SharpRiseScorer.calc_score(s, pm) for s in dm._ind_cache}
    decl = {s: SharpDeclineScorer.calc_score(s, pm) for s in dm._ind_cache}
    assert rise["CUTUSDT"]["scores"]["player"] == 2 and rise["CUTUSDT"]["has_rise_tag"]
    assert decl["HUNTUSDT"]["scores"]["player"] == 2        # 상세 갱신 종목이 아니어도 가산
    assert decl["WSELLUSDT"]["scores"]["player"] == 2       # 고래 매도 = 하락 태그
    assert rise["HUNTUSDT"]["scores"]["player"] == 0
    assert rise["NONEUSDT"]["scores"]["player"] == 0 and decl["NONEUSDT"]["scores"]["player"] == 0


def test_col3_energy_player_bonus_matches_scorer(dm):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        cases = [("Sharp rise", "CUTUSDT"), ("Sharp decline", "WSELLUSDT"), ("Sharp rise", "HUNTUSDT")]
        for mode, sym in cases:
            p = MiddlePanel.__new__(MiddlePanel)
            p._energy_f = tk.Frame(root)
            p._sel_var = tk.StringVar(root, sym)
            p._sort_mode = mode
            p._refresh_energy()
            texts = [w.cget("text") for f in p._energy_f.winfo_children()
                     for w in f.winfo_children() if isinstance(w, tk.Label)]
            score = (SharpRiseScorer if mode == "Sharp rise" else SharpDeclineScorer).calc_score(sym)
            expected = "  ✅ +2/2점" if score["scores"]["player"] == 2 else "  — 0/2점"
            assert expected in texts, (mode, sym, texts)
    finally:
        root.destroy()
