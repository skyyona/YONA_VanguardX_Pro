"""
tests/middle/test_fourtf_fixes.py
1열 Sort by '4TF Optimization' 결함 수정·설계 변경 (2026-11-16) — 네트워크 없이 대역.
 T1·T7 지금 갱신되는 종목의 실제 지표(ind_ready)만 채점 — Gold 1위 4TF 점수도 같은 값
 T2 4점 이상 없으면 빈 목록 (기준 미달 대체 목록 삭제)
 T3 거래량 Top10 = 현재 순위 (캐시 생성 시 고정 값 아님)
 T5 일일 추세 중립 목록 제외
 설계 변경(T4 대체): FR중립·ATR적정 제거 · OI = 1시간 +3% · 롱숏균형 → 추세쏠림 · 10점 만점 · ATR 동점 정렬 제거
 T6 3열 배지 = 점수 함수 결과 · T8 3열 채점 보류·목록 밖·엔진 4TF 기본 조건 표시
 T9 1열 충족 = 만점 항목만 · 별점 10/7/5/3 · T10 2열 일치 기준 표시
"""
import inspect
import time

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.fourtf_scorer import FourTFScorer
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker


def _tf(d, k=50.0):
    return {"dir": d, "k": k, "d": k}


# 일일 ▲▲▲ · 단기 ▲▲▲▲ · 1m K 10 · ATR 4 · FR 0.01 · OI 1h +5 · 롱 65
_STRONG = dict(atr=4.0, atr_pct=4.0, funding_rate=0.01, oi_change=1.0, oi_change_1h=5.0, long_ratio=65.0,
               tf1=_tf("▲", 10.0), tf3=_tf("▲"), tf5=_tf("▲"), tf15=_tf("▲"),
               tf1h=_tf("▲"), tf4h=_tf("▲"), tf1d=_tf("▲"))


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager()
    tk = [SymbolTicker(f"S{i}USDT", 1.0, 0.0, 0.0, 1e9 - i, 1.0, 1.0) for i in range(200)]
    m._tickers = m._sorted_tickers = tk
    m._tkr_map = {t.symbol: t for t in tk}
    m._vol_rank = {t.symbol: i + 1 for i, t in enumerate(tk)}
    monkeypatch.setattr(ctx, "_data_mgr", m)
    return m


def _put(dm, sym, ready=True, **kw):
    ind = dict(dm._simple_ind(dm._tkr_map[sym]), **_STRONG)
    ind.update(kw)
    ind["_data_ready"] = True
    if ready:
        ind["_ls_ts"] = ind["_fr_ts"] = time.time()
    dm._ind_cache[sym] = ind


def _list(dm):
    dm._rebuild_ranking_rows()
    return [r[0] for r in FourTFScorer.get_sorted(dm.get_ranking_rows())]


# ── T1·T7 ─────────────────────────────────────────────────────────────
def test_t1_stale_symbol_outside_refresh_not_scored(dm):
    _put(dm, "S150USDT")                                   # 상위 100일 때 남은 옛 값 — 지금 151위
    r = FourTFScorer.calc_score("S150USDT")
    assert r["ready"] is False and r["total"] == 0
    assert _list(dm) == []                                 # 수정 전: ['S150USDT'] ★★★★★ 1위


def test_t1_ready_symbol_scored(dm):
    _put(dm, "S5USDT")
    r = FourTFScorer.calc_score("S5USDT")
    assert r["ready"] is True and r["total"] >= 4
    assert _list(dm) == ["S5USDT"]


def test_t7_fetch_failure_defaults_not_scored_and_gold_zero(dm):
    from middle.col1_ranking.ranking.gold_ranking import GoldRanking
    _put(dm, "S5USDT", ready=False, funding_rate=0.0, long_ratio=50.0)   # 롱숏·FR 조회 실패 기본값
    r = FourTFScorer.calc_score("S5USDT")
    assert r["ready"] is False and r["total"] == 0          # 수정 전: FR 기본값 0 → 'FR중립' +1 포함 채점
    # Gold 4TF 항목도 0 (봉 지표는 준비 — bars_ready True)
    assert dm.bars_ready("S5USDT") is True
    assert "tf_res[\"total\"] / tf_res[\"max\"]" in inspect.getsource(GoldRanking.calc)


# ── T2 대체 목록 삭제 ─────────────────────────────────────────────────
def test_t2_no_fallback_list_when_nothing_qualifies(dm):
    for i in range(100):                                   # 실제 종목 — 일일 중립 → 4점 미만
        _put(dm, f"S{i}USDT", tf1h=_tf("↔"), tf4h=_tf("↔"), tf1d=_tf("↔"), atr=1.0, atr_pct=1.0, oi_change=-1.0)
    assert all(FourTFScorer.calc_score(f"S{i}USDT")["total"] < 4 for i in range(100))
    assert _list(dm) == []                                 # 수정 전: 30행(기본값 2.0 ATR 행이 동점 정렬로 우선)


def test_t2_startup_empty(dm):
    assert _list(dm) == []                                 # 시작 직후(캐시 없음) — 수정 전: 거래량 순서 30행


# ── T3 거래량 Top10 = 현재 순위 ─────────────────────────────────────────
def test_t3_volume_rank_live_not_frozen(dm):
    _put(dm, "S5USDT")
    _put(dm, "S90USDT")
    dm._ind_cache["S5USDT"]["volume"] = {"rank": 6, "usd_b": 1.0}     # 캐시 생성 당시 6위
    dm._ind_cache["S90USDT"]["volume"] = {"rank": 91, "usd_b": 0.1}   # 캐시 생성 당시 91위
    dm._vol_rank["S5USDT"], dm._vol_rank["S90USDT"] = 80, 2           # 지금 순위
    a, b = FourTFScorer.calc_score("S5USDT"), FourTFScorer.calc_score("S90USDT")
    assert (a["vol_rank"], a["scores"]["volume"]) == (80, 0)          # 수정 전: 6위 → 1점
    assert (b["vol_rank"], b["scores"]["volume"]) == (2, 1)           # 수정 전: 91위 → 0점


def test_t3_helper_without_manager(monkeypatch):
    monkeypatch.setattr(ctx, "_data_mgr", None)
    assert ctx.get_vol_rank("BTCUSDT") == 999


# ── T5 일일 추세 중립 제외 ─────────────────────────────────────────────
def test_t5_neutral_daily_trend_excluded(dm, monkeypatch):
    _put(dm, "S1USDT", tf1h=_tf("↔"), tf4h=_tf("↔"), tf1d=_tf("↔"))
    r = FourTFScorer.calc_score("S1USDT")
    assert r["base_dir"] is None
    # 설계 변경(FR·ATR 제거) 후 방향 무관 항목은 거래량Top10·OI 1h 최대 2점 → 4점 미만이지만, 필터로도 명시 제외
    assert r["total"] == 2 and _list(dm) == []
    real = FourTFScorer.calc_score
    monkeypatch.setattr(FourTFScorer, "calc_score",
                        staticmethod(lambda s: dict(real(s), total=6)))   # 다른 방향 무관 점수가 생겨도
    assert _list(dm) == []                                 # 수정 전 필터면 목록 포함


# ── 설계 변경: FR·ATR 항목 제거 · OI = 1시간 +3% · 롱숏균형 → 추세쏠림 · 10점 만점 ─────────
def test_design_items_and_max(dm):
    _put(dm, "S1USDT")
    r = FourTFScorer.calc_score("S1USDT")
    assert set(r["scores"]) == {"align", "entry", "macro", "volume", "oi", "balance"} and r["max"] == 10
    # 일일 ▲▲▲(2)·단기 ▲×4(4)·1m K 10(1)·거래량 2위(1)·OI 1h +5(1)·롱 65(1) = 10
    assert r["total"] == 10


@pytest.mark.parametrize("fr, atr", [(0.0, 4.0), (0.5, 4.0), (0.01, 15.0), (0.01, 1.0)])
def test_design_fr_and_atr_do_not_change_total(dm, fr, atr):
    _put(dm, "S1USDT")
    base = FourTFScorer.calc_score("S1USDT")["total"]
    _put(dm, "S1USDT", funding_rate=fr, atr=atr, atr_pct=atr)
    assert FourTFScorer.calc_score("S1USDT")["total"] == base   # 수정 전: FR 중립·ATR 3~8% 각 ±1


@pytest.mark.parametrize("oi10, oi1h, pts", [(+5.0, 0.5, 0), (-5.0, 3.01, 1), (+1.0, 3.0, 0), (0.0, 12.0, 1)])
def test_design_oi_uses_1h_over_3pct(dm, oi10, oi1h, pts):
    _put(dm, "S1USDT", oi_change=oi10, oi_change_1h=oi1h)
    r = FourTFScorer.calc_score("S1USDT")
    assert r["scores"]["oi"] == pts and r["oi"] == oi1h          # 수정 전: 10분 OI > 0


def test_design_tie_not_sorted_by_atr(dm):
    _put(dm, "S3USDT", atr=15.0, atr_pct=15.0)             # 동점 — 수정 전 ATR 높은 순으로 1위
    _put(dm, "S4USDT", atr=1.0, atr_pct=1.0)
    assert _list(dm) == ["S3USDT", "S4USDT"]               # 동점 = 거래량 순서
    _put(dm, "S3USDT", atr=1.0, atr_pct=1.0)
    _put(dm, "S4USDT", atr=15.0, atr_pct=15.0)
    assert _list(dm) == ["S3USDT", "S4USDT"]


# ── T6·T8 3열 표시 ─────────────────────────────────────────────────
def _tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    return root


def _walk_texts(w):
    import tkinter as tk
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Label):
            out.append(c.cget("text"))
        out.extend(_walk_texts(c))
    return out


def _verdict(sym, sorted_rows):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    root = _tk_root()
    try:
        p = MiddlePanel.__new__(MiddlePanel)
        p._verdict_f = tk.Frame(root)
        p._sel_var = tk.StringVar(root, sym)
        p._sort_mode = "4TF Optimization"
        p._get_phase_for_sym = lambda s: ("", "")
        p._render_forecast = lambda s: None
        p._get_sorted_ranking = lambda: sorted_rows
        p._refresh_verdict()
        return _walk_texts(p._verdict_f)
    finally:
        root.destroy()


def test_t8_not_ready_held_and_outside_list(dm):
    dm._rebuild_ranking_rows()
    _put(dm, "S150USDT")
    t = _verdict("S150USDT", [])
    assert any("4TF Optimization 채점 보류" in x for x in t) and not any("None위" in x for x in t)
    _put(dm, "S1USDT", tf1h=_tf("↔"), tf4h=_tf("↔"), tf1d=_tf("↔"))
    t = _verdict("S1USDT", [])
    assert any(x.startswith("목록 밖 (4점 미만·일일 중립·50위 밖) · 총 2/10점") for x in t), t


def test_t8_engine_basic_condition_line(dm, monkeypatch):
    from bottom_engine.models import StrategyParams
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default",
                        staticmethod(lambda m: StrategyParams(sort_mode=m, stop_loss=0.8, leverage=20)))
    dm._rebuild_ranking_rows()
    _put(dm, "S1USDT", atr=2.5, atr_pct=2.5, tf5=_tf("▲", 30.0))
    t = _verdict("S1USDT", [("S1USDT",)])
    assert "엔진 4TF 기본 조건: ATR 2.50% (1.85~6.0) ✅ · 5분 K 30 (롱 ≤35) ✅ — 다른 진입 조건 별도" in t, t
    _put(dm, "S1USDT", atr=7.0, atr_pct=7.0, tf5=_tf("▲", 50.0))
    t = _verdict("S1USDT", [("S1USDT",)])
    assert "엔진 4TF 기본 조건: ATR 7.00% (1.85~6.0) ❌ · 5분 K 50 (롱 ≤35) ❌ — 다른 진입 조건 별도" in t, t


def test_t6_col3_badges_match_scorer():
    import middle.widget.panel_col3 as pc3
    src = inspect.getsource(pc3)
    assert 'self._calc_4tf_score(sym)["scores"]["balance"] == 1' in src            # 롱숏 배지 = 점수 함수
    assert '_res4b["scores"]["oi"] == 1' in src                                   # OI 배지 = 점수 함수
    assert "🎯 FR중립" not in src and "4TF 적정 변동성 (3~8%)" not in src           # 제거 항목 배지 없음
    assert "lsa.score_4tf" not in src and "fra.score_4tf" not in src


# ── T9 1열 충족 문구 = 만점 항목만 ─────────────────────────────────────────
def test_t9_col1_met_items_full_marks_only_and_stars(dm):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    root = _tk_root()
    try:
        _put(dm, "S1USDT")                                   # 10/10 — 6/6 충족
        _put(dm, "S2USDT", tf3=_tf("▼"), tf5=_tf("▼"), tf15=_tf("▼"), tf1d=_tf("▼"))   # 단기일치 1/4·일일강도 1/2
        p = MiddlePanel.__new__(MiddlePanel)
        p._app_state, p._sort_mode = "RANKING", "4TF Optimization"
        p._inner, p._verdict_f = tk.Frame(root), tk.Frame(root)
        p._row_frames, p._special, p._cum_labels, p._change_labels, p._phase_labels = [], {}, {}, {}, {}
        p._m4_labels, p._nl_rows, p._player_tags_map, p._gold_sym = {}, {}, {}, ""
        p._time_fixed, p._time_fix_prices = False, {}
        p._sel_var = tk.StringVar(root, "")
        dm._rebuild_ranking_rows()
        p._build_ranking_rows(FourTFScorer.get_sorted(dm.get_ranking_rows()))
        rows = {s: _walk_texts(f) for f, s in p._row_frames}
        r2 = FourTFScorer.calc_score("S2USDT")
        assert r2["scores"]["align"] == 1 and r2["scores"]["macro"] == 1
        assert "★★★★★" in rows["S1USDT"] and any("✅ 6/6 전부 충족!  (총 10/10점)" in x for x in rows["S1USDT"])
        # 수정 전: 부분 점수도 충족으로 세어 '8/8 전부 충족'
        assert any("✅ 4/6 충족 · 부족: 단기일치, 일일강도" in x for x in rows["S2USDT"]), rows["S2USDT"]
    finally:
        root.destroy()


# ── T10 2열 4TF COMPLETE ALIGNMENT 기준 표시 ──────────────────────────────
def test_t10_col2_alignment_basis_label():
    import middle.widget.panel_col2 as pc2
    assert "단기 다수 방향 기준 (1열·3열 단기일치 = 일일 방향 기준)" in inspect.getsource(pc2)


def test_orphan_score_4tf_removed():
    from middle.col3_analysis_panels.derivative_analysis.funding_rate import FundingRatePanel
    from middle.col3_analysis_panels.derivative_analysis.longshort_ratio import LongShortPanel
    assert not hasattr(FundingRatePanel.from_rate(0.01), "score_4tf")
    assert not hasattr(LongShortPanel.from_pct(50.0), "score_4tf")
    assert LongShortPanel.analyze(None).warning == ""
