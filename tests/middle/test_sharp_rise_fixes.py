"""
tests/middle/test_sharp_rise_fixes.py
1열 Sort by 'Sharp rise' 결함 수정 (2026-11-16) — 네트워크 없이 대역.
 A 지금 갱신되는 종목의 실제 지표만 채점 (거래량 101~200위 옛 값·시작 직후 기본값 제외)
 E 자격: 숏 50% 이상(숏 다수) 또는 FR < −0.01%
 C 숏 청산 근접 항목 제외 (13점 만점, 엔진 청산 값은 그대로)
 D Player 가산 태그에서 'FR-' 제외 (펀딩비 이중 가점 제거)
 B OI 항목 = 1시간 OI 증가율(부호 유지) +3% 1점 · +8% 2점 — 요청 1회(5m 13개), 기존 10분 값 그대로
 F 3열: 목록 밖 순위 표시·OI(1h) 부호·채점 보류 문구
"""
import inspect

import pytest

import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.sharp_rise_scorer import SharpRiseScorer
import middle.data.data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker

# 숏 75%·FR −0.2%·VSS 2.0 — 강한 숏 쏠림 지표
_STRONG = dict(long_ratio=25.0, funding_rate=-0.2, liq_short_pct=1.2, vss=2.0, oi_change=0.0)


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
    return [r[0] for r in SharpRiseScorer.get_sorted(dm.get_ranking_rows())]


def test_a_stale_values_outside_refresh_set_not_scored(dm):
    _put(dm, "S150USDT")                                   # 151위 — 상위 100일 때 남은 옛 값
    r = SharpRiseScorer.calc_score("S150USDT")
    assert r["ready"] is False and r["qualified"] is False
    assert _list(dm) == []                                 # 수정 전: ['S150USDT'] (옛 지표로 1위)


def test_a_defaults_never_fill_list(dm):
    # 갱신 대상 밖 100종목 = 기본값(롱 50%) — 수정 전: 전부 자격(2점) → 4점 이상 없으면 목록을 채움
    assert all(not SharpRiseScorer.calc_score(f"S{i}USDT")["qualified"] for i in range(100, 200))
    assert _list(dm) == []


def test_a_refresh_set_requires_both_stages(dm):
    _put(dm, "S5USDT", stage2=False)                       # STAGE3만 (시작 직후 롱숏·FR 기본값)
    assert SharpRiseScorer.calc_score("S5USDT")["ready"] is False
    _put(dm, "S6USDT", data=False)                         # STAGE2만 (봉 지표 기본값)
    assert SharpRiseScorer.calc_score("S6USDT")["ready"] is False
    _put(dm, "S7USDT")                                     # 둘 다 반영
    r = SharpRiseScorer.calc_score("S7USDT")
    assert r["ready"] is True and r["qualified"] is True
    assert _list(dm) == ["S7USDT"]


def test_a_selected_or_engine_symbol_uses_detail_values(dm):
    # 상세 갱신(선택·엔진 종목)은 _data_ready만 붙임 — 거래량 순위와 무관하게 실제 값
    _put(dm, "S160USDT", stage2=False)
    assert SharpRiseScorer.calc_score("S160USDT")["ready"] is False
    dm._last_detail_sym = "S160USDT"
    assert SharpRiseScorer.calc_score("S160USDT")["ready"] is True
    dm._last_detail_sym, dm._engine_sym = "", "S160USDT"
    assert SharpRiseScorer.calc_score("S160USDT")["ready"] is True


def test_a_no_manager_not_ready(monkeypatch):
    monkeypatch.setattr(ctx, "_data_mgr", None)
    assert ctx.ind_ready("BTCUSDT") is False


# ── E 자격: 숏 50% 이상(숏 다수) 또는 FR < −0.01% ─────────────────────
@pytest.mark.parametrize("long_ratio, fr, qualified", [
    (55.0, 0.0, False),     # 숏 45% — 수정 전 자격(≥40%)
    (60.0, 0.005, False),   # 숏 40% 경계 — 수정 전 자격
    (50.0, 0.0, True),      # 숏 50% 경계 — 자격
    (40.0, 0.01, True),     # 숏 60%
    (70.0, -0.02, True),    # 숏 30%여도 FR 음수(숏 비용) — 자격
    (70.0, -0.01, False),   # FR −0.01% 경계는 미달 (< −0.01)
])
def test_e_qualification_short_majority_or_negative_fr(dm, long_ratio, fr, qualified):
    _put(dm, "S3USDT", long_ratio=long_ratio, funding_rate=fr)
    assert SharpRiseScorer.calc_score("S3USDT")["qualified"] is qualified


def test_e_score_start_matches_qualification():
    # 숏쏠림 점수는 50%부터 1점 — 자격 기준과 같은 시작점 (자격 없이 점수만 받는 구간 없음)
    import inspect
    src = inspect.getsource(SharpRiseScorer.calc_score)
    assert "1 if sr >= 50" in src and "(sr >= 50.0)" in src


# ── C 숏 청산 근접 항목 제외 (13점 만점) ──────────────────────────────
def test_c_liquidation_estimate_not_scored(dm):
    # 같은 숏 쏠림·FR에서 청산 근접 값(=저변동일수록 가까움)이 달라도 점수 같음
    _put(dm, "S1USDT", liq_short_pct=0.79)                 # 수정 전 3점 (AAPL 실측 0.79)
    _put(dm, "S2USDT", liq_short_pct=5.0)                  # 수정 전 0점
    a, b = SharpRiseScorer.calc_score("S1USDT"), SharpRiseScorer.calc_score("S2USDT")
    assert a["total"] == b["total"] and a["max"] == b["max"] == 13
    assert "liq" not in a["scores"] and "liq_s" not in a
    assert set(a["scores"]) == {"sr", "fr", "oi", "player", "vss"}


def test_c_engine_liq_value_untouched(dm):
    _put(dm, "S1USDT", liq_short_pct=0.79)
    SharpRiseScorer.calc_score("S1USDT")
    assert dm._ind_cache["S1USDT"]["liq_short_pct"] == 0.79   # 엔진 G8·3열 청산 패널 입력 그대로


def test_c_max_score_reachable(dm):
    # 숏 80%·FR −0.06%·VSS 1.6 — Player·OI 없이 4+3+2 = 9
    _put(dm, "S1USDT", long_ratio=20.0, funding_rate=-0.06, vss=1.6)
    r = SharpRiseScorer.calc_score("S1USDT")
    assert r["scores"] == {"sr": 4, "fr": 3, "oi": 0, "player": r["scores"]["player"], "vss": 2}


def test_c_star_thresholds_same_ratio():
    import inspect, math
    import middle.widget.panel_col1 as pc1
    assert [math.ceil(13 * t / 16) for t in (14, 11, 8, 5)] == [12, 9, 7, 5]
    src = inspect.getsource(pc1)
    assert '(12, 9, 7, 5) if self._sort_mode == "Sharp rise" else (14, 11, 8, 5)' in src
    assert "청산+{_res['liq_s']" not in src


# ── D 펀딩비 이중 가점 제거 — Player 가산 태그에서 'FR-' 제외 ─────────────
def test_d_fr_minus_tag_alone_no_player_bonus(dm):
    # FR −0.2% → FR 항목 3점 + 'FR-' 태그 (같은 조건) — 수정 전 Player 2점 추가(펀딩비 하나로 5점)
    _put(dm, "S1USDT", vss=1.0, bpr=0.5, oi_change=0.0)
    det = dm.get_player("S1USDT")
    assert det.keys == ["FR-"] and det.has_rise_tag          # 태그 감지·3열 방향 표시는 그대로
    for pm in (None, ctx.get_player_map()):
        r = SharpRiseScorer.calc_score("S1USDT", pm)
        assert r["scores"]["fr"] == 3 and r["scores"]["player"] == 0 and r["has_rise_tag"] is False


@pytest.mark.parametrize("extra, tag", [
    (dict(vss=3.0, bpr=0.7), "고래 매수"),
    (dict(oi_change=12.0, vss=1.6, price_change_pct=1.0), "세력 매집"),
    (dict(long_ratio=70.0, funding_rate=-0.02, oi_change=9.0), "기관 유입"),
])
def test_d_other_rise_tags_keep_bonus(dm, extra, tag):
    _put(dm, "S1USDT", **extra)
    assert tag in dm.get_player("S1USDT").keys
    for pm in (None, ctx.get_player_map()):
        r = SharpRiseScorer.calc_score("S1USDT", pm)
        assert r["scores"]["player"] == 2 and r["has_rise_tag"] is True


def test_d_player_keys_and_map_keys(dm):
    from middle.analysis.tag_detector import TagDetector
    assert SharpRiseScorer.PLAYER_KEYS == {"고래 매수", "세력 매집", "기관 유입"}
    assert TagDetector.RISE_KEYS == {"고래 매수", "세력 매집", "기관 유입", "FR-"}   # 3열 방향·메시지용은 그대로
    _put(dm, "S1USDT", vss=3.0, bpr=0.7)
    pm = ctx.get_player_map(["S1USDT"])
    assert pm["S1USDT"]["keys"] == dm.get_player("S1USDT").keys        # 절단 전 전체


def test_d_col3_bonus_display_matches_score(dm):
    import tkinter as tk
    from middle.widget.middle_panel import MiddlePanel
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk 디스플레이 없음")
    root.withdraw()
    try:
        _put(dm, "S1USDT", vss=1.0, bpr=0.5)                    # FR- 단독
        _put(dm, "S2USDT", vss=3.0, bpr=0.7)                    # FR- + 고래 매수
        for sym, expected in (("S1USDT", "  — 0/2점"), ("S2USDT", "  ✅ +2/2점")):
            p = MiddlePanel.__new__(MiddlePanel)
            p._energy_f = tk.Frame(root)
            p._sel_var = tk.StringVar(root, sym)
            p._sort_mode = "Sharp rise"
            p._refresh_energy()
            texts = [w.cget("text") for f in p._energy_f.winfo_children()
                     for w in f.winfo_children() if isinstance(w, tk.Label)]
            assert expected in texts, (sym, texts)
            assert SharpRiseScorer.calc_score(sym)["scores"]["player"] == (2 if "✅" in expected else 0)
    finally:
        root.destroy()


# ── B OI 항목 = 1시간 OI 증가율 (부호 유지, +3% 1점 · +8% 2점) ────────────
@pytest.mark.parametrize("oi_1h, pts", [(-12.0, 0), (0.0, 0), (3.0, 0), (3.01, 1), (8.0, 1), (8.01, 2), (13.19, 2)])
def test_b_oi_1h_signed_thresholds(dm, oi_1h, pts):
    _put(dm, "S1USDT", oi_change=-20.0, oi_change_1h=oi_1h)   # 10분 값은 OI 항목에 쓰지 않음
    r = SharpRiseScorer.calc_score("S1USDT")
    assert r["scores"]["oi"] == pts and r["oi"] == oi_1h        # 수정 전: |−20| > 15 → 2점 (감소도 가점)


def _hist(vals):
    return [{"sumOpenInterest": str(v), "timestamp": i} for i, v in enumerate(vals)]


def test_b_fetch_changes_one_request_same_10min_value():
    import types
    from middle.data.open_interest_data import OpenInterestFetcher, _change_pct
    vals = [100.0 + i for i in range(12)] + [120.0]            # 13개: 100 → 120 (1시간 +20%)
    calls = []
    client = types.SimpleNamespace(fetch_open_interest_hist=lambda s, p, n: calls.append((s, p, n)) or _hist(vals)[-n:])
    f = OpenInterestFetcher(client)
    chg10, chg1h = f.fetch_changes("AUSDT")
    assert calls == [("AUSDT", "5m", 13)]                        # 요청 1회 (기존 limit 3 → 13)
    assert chg10 == _change_pct(_hist(vals)[-3:]) == (120.0 - 110.0) / 110.0 * 100.0   # 기존 limit 3 응답과 같은 식
    assert chg1h == (120.0 - 100.0) / 100.0 * 100.0


def test_b_fetch_changes_short_history_and_bad_values():
    import types
    from middle.data.open_interest_data import OpenInterestFetcher
    f = OpenInterestFetcher(types.SimpleNamespace(fetch_open_interest_hist=lambda s, p, n: _hist([100.0, 101.0, 102.0])))
    assert f.fetch_changes("NEWUSDT") == (2.0, 0.0)              # 13개 미만(신규 상장) → 1시간 0.0
    f = OpenInterestFetcher(types.SimpleNamespace(fetch_open_interest_hist=lambda s, p, n: []))
    assert f.fetch_changes("XUSDT") == (0.0, 0.0)                # 조회 실패


def test_b_stage2_and_detail_store_1h(dm):
    import types
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (1.25, 6.5))
    dm._client.fetch_all_premium_index = lambda: []
    dm._refresh_topn_scores(1)
    ind = dm._ind_cache["S0USDT"]
    assert (ind["oi_change"], ind["oi_change_1h"]) == (1.25, 6.5)
    assert "oi_change_1h" in dm_mod._STAGE2_FIELDS               # STAGE3 병합이 되돌리지 않음
    src = inspect.getsource(MiddleDataManager._refresh_detail)
    assert "oi, oi_1h = self._oi_svc.fetch_changes(symbol)" in src and "(fr, oi, ls, oi_1h)" in src
    assert '"oi_change_1h": oi_1h' in inspect.getsource(MiddleDataManager._build_ind_dict)


def test_b_detail_refresh_end_to_end_stores_1h(dm):
    # 상세 갱신 실제 실행 — _compute_detail → _build_ind_dict 까지 oi_1h 전달 (NameError 회귀 방지)
    import types
    from middle.models import OHLCVBar
    step = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    def bars(tf, n):
        return [OHLCVBar(i * step[tf], 1 + i * 1e-3, 1.01 + i * 1e-3, 0.99 + i * 1e-3, 1 + i * 1e-3, 100.0 + i % 7,
                         100.0, i * step[tf] + step[tf] - 1) for i in range(n)]
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: bars(tf, limit - 1))
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.5, 9.25))
    dm._refresh_detail("S0USDT")
    assert dm._last_refresh_error == ""
    ind = dm._ind_cache["S0USDT"]
    assert (ind["oi_change"], ind["oi_change_1h"], ind["_data_ready"]) == (0.5, 9.25, True)
    assert dm._deriv_cache["S0USDT"][3] == 9.25                 # WS 봉 마감 재계산도 같은 값 사용


# ── F 3열 Sharp rise 선정 근거 표시 ──────────────────────────────────
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
        p._sort_mode = "Sharp rise"
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
    _put(dm, "S1USDT", long_ratio=45.0, funding_rate=-0.02, vss=1.0, oi_change_1h=0.0)   # 자격 O · 숏 55% 1점 + FR 1점 = 2점(4점 미만)
    texts = _verdict_texts("S1USDT", [])
    assert any("목록 밖 (4점 미만·20위 밖) · 총 2/13점" in t for t in texts), texts
    assert not any("None위" in t for t in texts)


def test_f_rank_in_list_and_signed_oi(dm):
    _put(dm, "S1USDT", oi_change_1h=-4.2)
    texts = _verdict_texts("S1USDT", [("S1USDT",)])
    assert any(t.startswith("전체 1위 · 총 ") and t.endswith("/13점") for t in texts), texts
    assert any("OI(1h) -4.2%(+0)" in t for t in texts), texts   # 수정 전: 절댓값 '+4.2%'


def test_f_not_ready_distinct_message(dm):
    _put(dm, "S150USDT")                                        # 갱신 대상 밖 옛 값
    texts = _verdict_texts("S150USDT", [])
    assert any("채점 보류 (갱신 대상 밖·데이터 준비 중)" in t for t in texts), texts
    assert not any("자격 미달" in t for t in texts)
