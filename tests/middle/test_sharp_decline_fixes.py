"""
tests/middle/test_sharp_decline_fixes.py
1열 Sort by 'Sharp decline' 결함 수정 (2026-11-16, Sharp rise c35c7e3와 같은 방식) — 네트워크 없이 대역.
 A 지금 갱신되는 종목의 실제 지표만 채점 (거래량 101~200위 옛 값·시작 직후 기본값 제외)
 E 자격: 롱 50% 이상 그리고 FR ≥ 0 (숏 비용 FR 음수 종목 제외)
 C 롱 청산 근접 항목 제외 (13점 만점, 엔진 청산 값은 그대로) — 1열 별점 12/9/7/5 단일 기준
 D Player 가산 태그에서 FR+ 과열·롱 스퀴즈·FOMO 극단 제외 (롱비율·FR 이중 가점 제거)
 B OI 항목 = 1시간 OI 증가율(증가만) +3% 1점 · +8% 2점
 F 3열: 목록 밖 순위·OI(1h) 부호·채점 보류·미달 조건만 표시
"""
import inspect

import pytest

import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.sharp_decline_scorer import SharpDeclineScorer
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker

# 롱 75%·FR +0.06%·VSS 2.0 — 강한 롱 쏠림 지표
_STRONG = dict(long_ratio=75.0, funding_rate=0.06, liq_long_pct=-1.2, vss=2.0, oi_change=0.0, oi_change_1h=0.0)


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager()
    tk = [SymbolTicker(f"S{i}USDT", 1.0, 0.0, 0.0, 1e9 - i, 1.0, 1.0) for i in range(200)]
    m._tickers = m._sorted_tickers = tk
    m._tkr_map = {t.symbol: t for t in tk}
    m._vol_rank = {t.symbol: i + 1 for i, t in enumerate(tk)}
    monkeypatch.setattr(ctx, "_data_mgr", m)
    return m


def _put(dm, sym, stage2=True, data=True, **kw):
    ind = dict(dm._simple_ind(dm._tkr_map[sym]), **_STRONG)
    ind.update(kw)
    ind["_data_ready"] = data
    if stage2:
        ind["_stage2_ready"] = True
    dm._ind_cache[sym] = ind


def _list(dm):
    dm._rebuild_ranking_rows()
    return [r[0] for r in SharpDeclineScorer.get_sorted(dm.get_ranking_rows())]


def test_a_stale_values_outside_refresh_set_not_scored(dm):
    _put(dm, "S150USDT")                                   # 151위 — 상위 100일 때 남은 옛 값
    r = SharpDeclineScorer.calc_score("S150USDT")
    assert r["ready"] is False and r["qualified"] is False
    assert _list(dm) == []                                 # 수정 전: ['S150USDT'] (옛 지표로 1위)


def test_a_defaults_never_fill_list(dm):
    # 기본값(롱 50%) — 수정 전: 전부 자격(2점) → 4점 이상 없으면 목록을 채움
    assert all(not SharpDeclineScorer.calc_score(f"S{i}USDT")["qualified"] for i in range(200))
    assert _list(dm) == []


def test_a_refresh_set_requires_both_stages(dm):
    _put(dm, "S5USDT", stage2=False)
    assert SharpDeclineScorer.calc_score("S5USDT")["ready"] is False
    _put(dm, "S6USDT", data=False)
    assert SharpDeclineScorer.calc_score("S6USDT")["ready"] is False
    _put(dm, "S7USDT")
    r = SharpDeclineScorer.calc_score("S7USDT")
    assert r["ready"] is True and r["qualified"] is True
    assert _list(dm) == ["S7USDT"]


def test_a_selected_or_engine_symbol_uses_detail_values(dm):
    _put(dm, "S160USDT", stage2=False)
    assert SharpDeclineScorer.calc_score("S160USDT")["ready"] is False
    dm._last_detail_sym = "S160USDT"
    assert SharpDeclineScorer.calc_score("S160USDT")["ready"] is True
    dm._last_detail_sym, dm._engine_sym = "", "S160USDT"
    assert SharpDeclineScorer.calc_score("S160USDT")["ready"] is True


def test_a_gold_gets_no_decline_credit_from_stale(dm):
    from middle.col1_ranking.ranking.gold_ranking import GoldRanking
    _put(dm, "S150USDT")
    r = SharpDeclineScorer.calc_score("S150USDT")
    assert r["qualified"] is False                         # Gold ▼·중립 경로 squeeze = 0 (qualified 기준)
    assert "decl_res[\"qualified\"]" in inspect.getsource(GoldRanking.calc)


# ── E 자격: 롱 50% 이상 그리고 FR ≥ 0 ──────────────────────────────────
@pytest.mark.parametrize("long_ratio, fr, qualified", [
    (50.0, 0.0, True),      # 롱 50%·FR 0 경계 — 자격
    (49.9, 0.2, False),     # 롱 50% 미만
    (70.0, -0.0001, False), # FR 음수(숏 비용) — 수정 전 자격
    (52.0, -0.2, False),    # 실측 유형: 롱 다수지만 FR −0.2% (상승 태그 FR-) — 수정 전 자격
    (85.0, 0.12, True),
])
def test_e_qualification_long_majority_and_fr_not_negative(dm, long_ratio, fr, qualified):
    _put(dm, "S3USDT", long_ratio=long_ratio, funding_rate=fr)
    assert SharpDeclineScorer.calc_score("S3USDT")["qualified"] is qualified


# ── C 롱 청산 근접 항목 제외 (13점 만점) ──────────────────────────────
def test_c_liquidation_estimate_not_scored(dm):
    _put(dm, "S1USDT", liq_long_pct=-0.65)                 # 수정 전 3점 (ANTHROPIC 실측 0.65 — 저변동)
    _put(dm, "S2USDT", liq_long_pct=-5.0)                  # 수정 전 0점
    a, b = SharpDeclineScorer.calc_score("S1USDT"), SharpDeclineScorer.calc_score("S2USDT")
    assert a["total"] == b["total"] and a["max"] == b["max"] == 13
    assert "liq" not in a["scores"] and "liq_l" not in a
    assert set(a["scores"]) == {"lr", "fr", "oi", "player", "vss"}


def test_c_engine_liq_value_untouched(dm):
    _put(dm, "S1USDT", liq_long_pct=-0.65)
    SharpDeclineScorer.calc_score("S1USDT")
    assert dm._ind_cache["S1USDT"]["liq_long_pct"] == -0.65   # 엔진 G8·3열 청산 패널 입력 그대로


def test_c_col1_single_13pt_star_scale_and_no_liq_alert():
    import middle.widget.panel_col1 as pc1
    src = inspect.getsource(pc1)
    assert "_t5, _t4, _t3, _t2 = (12, 9, 7, 5)" in src and "(14, 11, 8, 5)" not in src
    assert "청산-{_res['liq_l']" not in src


# ── D 롱비율·FR 이중 가점 제거 — Player 가산 태그에서 FR+ 과열·롱 스퀴즈·FOMO 극단 제외 ──
@pytest.mark.parametrize("kw, tags", [
    (dict(long_ratio=60.0, funding_rate=0.11), {"FR+ 과열"}),                          # FR 3점과 같은 조건
    (dict(long_ratio=86.0, funding_rate=0.11), {"FR+ 과열", "롱 스퀴즈", "FOMO 극단"}),   # 롱 4점·FR 3점과 같은 조건
])
def test_d_lr_fr_condition_tags_no_bonus(dm, kw, tags):
    _put(dm, "S1USDT", vss=1.0, bpr=0.5, atr=1.0, **kw)
    det = dm.get_player("S1USDT")
    assert set(det.keys) == tags and det.has_decline_tag            # 태그 감지·3열 방향 표시는 그대로
    for pm in (None, ctx.get_player_map()):
        r = SharpDeclineScorer.calc_score("S1USDT", pm)
        assert r["scores"]["player"] == 0 and r["has_decline_tag"] is False   # 수정 전 2점


@pytest.mark.parametrize("kw, tag", [
    (dict(long_ratio=81.0, funding_rate=0.0, atr=3.5), "청산 헌터"),
    (dict(vss=3.0, bpr=0.2), "고래 매도"),
    (dict(oi_change=-6.0, price_change_pct=6.0), "세력 분산"),
])
def test_d_independent_tags_keep_bonus(dm, kw, tag):
    _put(dm, "S1USDT", **kw)
    assert tag in dm.get_player("S1USDT").keys
    for pm in (None, ctx.get_player_map()):
        r = SharpDeclineScorer.calc_score("S1USDT", pm)
        assert r["scores"]["player"] == 2 and r["has_decline_tag"] is True


def test_d_player_keys():
    from middle.analysis.tag_detector import TagDetector
    assert SharpDeclineScorer.PLAYER_KEYS == {"청산 헌터", "세력 분산", "고래 매도"}
    assert TagDetector.DECLINE_KEYS == {"FR+ 과열", "FOMO 극단", "롱 스퀴즈", "청산 헌터", "세력 분산", "고래 매도"}


def test_d_col3_bonus_display_matches_score(dm):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        _put(dm, "S1USDT", long_ratio=86.0, funding_rate=0.11, vss=1.0, bpr=0.5, atr=1.0)   # 롱·FR 태그만
        _put(dm, "S2USDT", long_ratio=86.0, funding_rate=0.11, vss=3.0, bpr=0.2, atr=1.0)   # + 고래 매도
        for sym, expected in (("S1USDT", "  — 0/2점"), ("S2USDT", "  ✅ +2/2점")):
            p = MiddlePanel.__new__(MiddlePanel)
            p._energy_f = tk.Frame(root)
            p._sel_var = tk.StringVar(root, sym)
            p._sort_mode = "Sharp decline"
            p._refresh_energy()
            texts = [w.cget("text") for f in p._energy_f.winfo_children()
                     for w in f.winfo_children() if isinstance(w, tk.Label)]
            assert expected in texts, (sym, texts)
            assert SharpDeclineScorer.calc_score(sym)["scores"]["player"] == (2 if "✅" in expected else 0)
    finally:
        root.destroy()


# ── B OI 항목 = 1시간 OI 증가율 (부호 유지, +3% 1점 · +8% 2점 — 증가만) ────────
@pytest.mark.parametrize("oi_1h, pts", [(-12.0, 0), (-6.0, 0), (0.0, 0), (3.0, 0), (3.01, 1), (8.0, 1), (8.01, 2), (13.19, 2)])
def test_b_oi_1h_signed_increase_only(dm, oi_1h, pts):
    _put(dm, "S1USDT", oi_change=-20.0, oi_change_1h=oi_1h)   # 10분 값은 OI 항목에 쓰지 않음
    r = SharpDeclineScorer.calc_score("S1USDT")
    assert r["scores"]["oi"] == pts and r["oi"] == oi_1h        # 수정 전: |−20| > 15 → 2점 (감소도 가점)


# ── F 3열 Sharp decline 선정 근거 표시 ────────────────────────────────
def _verdict_texts(sym, sorted_rows):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        p = MiddlePanel.__new__(MiddlePanel)
        p._verdict_f = tk.Frame(root)
        p._sel_var = tk.StringVar(root, sym)
        p._sort_mode = "Sharp decline"
        p._get_phase_for_sym = lambda s: ("", "")
        p._render_forecast = lambda s: None
        p._get_sorted_ranking = lambda: sorted_rows
        p._refresh_verdict()
        out = []
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    out.append(c.cget("text"))
                walk(c)
        walk(p._verdict_f)
        return out
    finally:
        root.destroy()


def test_f_rank_outside_list_not_none(dm):
    _put(dm, "S1USDT", long_ratio=55.0, funding_rate=0.01, vss=1.0)   # 자격 O · 롱 55% 1점 = 1점(4점 미만)
    texts = _verdict_texts("S1USDT", [])
    assert any("목록 밖 (4점 미만·30위 밖) · 총 1/13점" in t for t in texts), texts
    assert not any("None위" in t for t in texts)


def test_f_rank_in_list_and_signed_oi(dm):
    _put(dm, "S1USDT", oi_change_1h=-6.0)
    texts = _verdict_texts("S1USDT", [("S1USDT",)])
    assert any(t.startswith("전체 1위 · 총 ") and t.endswith("/13점") for t in texts), texts
    assert any("OI(1h) -6.0%(+0)" in t for t in texts), texts   # 수정 전: 절댓값 'OI +6.0%'
    assert not any("롱청산" in t for t in texts)


def test_f_not_ready_distinct_message(dm):
    _put(dm, "S150USDT")
    texts = _verdict_texts("S150USDT", [])
    assert any("채점 보류 (갱신 대상 밖·데이터 준비 중)" in t for t in texts), texts
    assert not any("자격 미달" in t for t in texts)


def test_f_not_qualified_message_mentions_fr(dm):
    _put(dm, "S1USDT", long_ratio=70.0, funding_rate=-0.05)
    texts = _verdict_texts("S1USDT", [])
    assert any("자격 미달 (FR -0.050% 음수)" in t for t in texts), texts          # 미달 조건만 (롱 70%는 충족)
    _put(dm, "S2USDT", long_ratio=45.0, funding_rate=0.02)
    texts = _verdict_texts("S2USDT", [])
    assert any("자격 미달 (롱쏠림 45% < 50%)" in t for t in texts), texts
