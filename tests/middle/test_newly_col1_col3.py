"""
tests/middle/test_newly_col1_col3.py
Newly Listed — 3열 종합분석 점수·순위가 1열에 표시한 같은 행(상장 경과일·24h 등락률)으로 계산되는지 검증.
1열 행 생성(_build_ranking_rows) → 3열 판정(_refresh_verdict) 실제 Tk 위젯 경로, 데이터 관리자는 대역.
"""
import tkinter as tk

import pytest

import middle.widget.shared_context as _ctx
from middle.col1_ranking.ranking.newlisted_scorer import NewlistedScorer
from middle.data.data_manager import MiddleDataManager
from middle.analysis.forecast import Forecaster
from middle.widget.middle_panel import MiddlePanel


def _row(sym, days, chg):
    return (sym, days, "─ 로딩중", "#888888", f"  {chg:+.2f}%", "#00ff00", f"{chg:+.2f}%", "#00ff00",
            "⟳ 전환 대기", "#ffff00", 4)


_NL_ROWS = [
    _row("N1USDT", 20, 12.0),    # VSS 2.5(+2)·OI 1h 6%(+1)·속도 +12%(+2)·FR 0(+0) = 5 × 1.3 = 6.5
    _row("N2USDT", 5, -25.0),    # 4 + 3 + 속도 0(하락 — 롱 방향만 가점, 2026-11-16) + 2 = 9 × 2.0 = 18.0
    _row("N3USDT", 10, 1.0),     # VSS 1.0·OI 1h 1% → 자격 미달 → 목록 제외 (2026-11-16 N3)
]
_IND = {
    "N1USDT": {"vss": 2.5, "oi_change_1h": 6.0, "funding_rate": 0.01},
    "N2USDT": {"vss": 4.2, "oi_change_1h": 21.0, "funding_rate": 0.12},
    "N3USDT": {"vss": 1.0, "oi_change_1h": 1.0, "funding_rate": 0.0},
}


class _DM:
    """Newly Listed 행·지표만 공급 — N1~N3은 거래량 상위 200(get_ranking_rows) 밖."""

    def get_newlisted_rows(self):
        return list(_NL_ROWS)

    def get_ranking_rows(self):
        return []

    def get_row(self, sym):   # 1열 행 단일 정의 대역 — 시세가 있는 종목(여기선 Newly 행)만 행 반환
        return next((r for r in _NL_ROWS if r[0] == sym), None)

    def get_ind(self, sym):
        return _IND.get(sym, {})

    get_player = MiddleDataManager.get_player   # Player 판정 단일 정의 (get_ind 기반)
    _ind_fresh = lambda self, sym: True          # 대역 지표 = 갱신 대상 값 (MiddleDataManager._ind_fresh)
    bars_ready = lambda self, sym: sym in _IND   # 대역 지표가 있는 종목 = 봉 지표 실제 값
    _forecaster = Forecaster(None)   # 가격 예고 판정식 없음 → 3열 '판정식 없음' 표시

    def get_forecast(self, sym):
        return None

    def get_listing_days(self, sym):
        return {r[0]: r[1] for r in _NL_ROWS}.get(sym, 0)

    def get_ticker(self, sym):
        return None


@pytest.fixture()
def panel(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    monkeypatch.setattr(_ctx, "_data_mgr", _DM())
    monkeypatch.setattr(_ctx, "_bl_mgr", None)
    p = MiddlePanel.__new__(MiddlePanel)
    p._app_state, p._sort_mode = "ANALYSIS", "Newly Listed"
    p._inner, p._verdict_f = tk.Frame(root), tk.Frame(root)
    p._row_frames, p._special, p._cum_labels, p._change_labels, p._phase_labels = [], {}, {}, {}, {}
    p._player_tags_map, p._gold_sym, p._nl_rows = {}, "", {}
    p._time_fixed, p._time_fix_prices = False, {}
    p._sel_var = tk.StringVar(root, "")
    p._build_ranking_rows()
    yield p
    root.destroy()


def _verdict_texts(p, sym):
    p._sel_var.set(sym)
    p._refresh_verdict()
    return [w.cget("text") for f in p._verdict_f.winfo_children()
            for w in f.winfo_children() if isinstance(w, tk.Label)]


def test_col1_shares_displayed_rows_in_order(panel):
    assert list(panel._nl_rows) == ["N2USDT", "N1USDT"]          # 자격 미달 N3 제외 (2026-11-16 N3)
    assert [s for _, s in panel._row_frames] == list(panel._nl_rows)
    assert panel._nl_rows["N1USDT"] == _NL_ROWS[0]


def test_col3_score_and_rank_match_col1_row(panel):
    res = NewlistedScorer.calc_score("N1USDT", _NL_ROWS[0])
    assert (res["total"], res["age_weight"], res["weighted"]) == (5, 1.3, 6.5)
    texts = _verdict_texts(panel, "N1USDT")
    assert "전체 2위 · 총 5/12점 × 연령가중 1.3 = 6.5점" in texts
    assert "Price Velocity 24h +12.00%(+2)  Funding Extreme 0.010%(+0)" in texts
    assert "전체 1위 · 총 9/12점 × 연령가중 2.0 = 18.0점" in _verdict_texts(panel, "N2USDT")


def test_col3_not_in_col1_list(panel):
    texts = _verdict_texts(panel, "OUTUSDT")
    assert "⚠ Newly Listed 대상 아님 (1열 목록 밖 — 상장 30일 초과·미상·주식/ETF·자격 미달 또는 상위 30위 밖)" in texts
    assert not any("선정 근거" in t for t in texts)


def test_col3_lifecycle_block_outside_top200(panel):
    """거래량 상위 200 밖 신규 상장 종목도 1열과 같은 상장 경과일로 생애주기 블록 표시."""
    texts = _verdict_texts(panel, "N2USDT")
    assert "★ Newly Listed 분석" in texts and " D+5 " in texts
