"""
tests/middle/test_newly_fixes.py
1열 Sort by 'Newly Listed' 결함 수정·사용자 결정 (2026-11-16) — 네트워크 없이 대역.
 ① 신규 상장(30일 이내·주식 제외)을 STAGE2·STAGE3 갱신 대상에 추가 → 실제 지표로 채점
 ③ 주식·ETF(underlyingType EQUITY 계열) 목록·추가 갱신 대상 제외 (원자재·FX·상장 전은 포함)
 N4 상장 24시간 미만(0일) 포함 · N1·N2 실제 봉 지표만 채점 · N3 자격 미달 제외 · N5 OI 1시간
 ② 롱 방향만 가점(가격 상승·OI 증가) · N6 3열 채점 보류 · N7 생애주기 1h OI·STAGE3 고점 대비 % · N8 도달 불가 코드 삭제
"""
import inspect
import time
import types

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.newlisted_scorer import NewlistedScorer
from middle.data.data_manager import MiddleDataManager
from middle.models import SymbolTicker

_DAY = 86_400_000


@pytest.fixture()
def dm(monkeypatch):
    m = MiddleDataManager()
    tk = [SymbolTicker(f"S{i}USDT", 1.0, 0.0, 0.0, 1e9 - i, 1.0, 1.0) for i in range(300)]
    m._tickers = m._sorted_tickers = tk
    m._tkr_map = {t.symbol: t for t in tk}
    m._vol_rank = {t.symbol: i + 1 for i, t in enumerate(tk)}
    now = int(time.time() * 1000)
    m._onboard_map = {t.symbol: now - 400 * _DAY for t in tk}            # 기본: 상장 400일
    monkeypatch.setattr(ctx, "_data_mgr", m)
    return m


def _listed(dm, sym, days, hours=0):
    dm._onboard_map[sym] = int(time.time() * 1000) - days * _DAY - hours * 3_600_000


# ── ③ 주식·ETF 판정 (exchangeInfo underlyingType) ───────────────────────────
def test_equity_set_from_exchange_info():
    ei = {"symbols": [
        {"symbol": "AMGNUSDT", "underlyingType": "EQUITY"}, {"symbol": "EWYUSDT", "underlyingType": "EQUITY"},
        {"symbol": "HKXUSDT", "underlyingType": "HK_EQUITY"}, {"symbol": "KRXUSDT", "underlyingType": "KR_EQUITY"},
        {"symbol": "CNXUSDT", "underlyingType": "CN_EQUITY"}, {"symbol": "XAUUSDT", "underlyingType": "COMMODITY"},
        {"symbol": "BTCUSDT", "underlyingType": "COIN"}, {"symbol": "ANTHROPICUSDT", "underlyingType": "PREMARKET"},
        {"symbol": "EURUSDT", "underlyingType": "FX"}]}
    assert dm_mod._build_equity_set(ei) == {"AMGNUSDT", "EWYUSDT", "HKXUSDT", "KRXUSDT", "CNXUSDT"}


def test_fetch_onboard_map_also_sets_equity(dm):
    now = int(time.time() * 1000)
    dm._client = types.SimpleNamespace(fetch_exchange_info=lambda: {"symbols": [
        {"symbol": "AMGNUSDT", "onboardDate": now, "underlyingType": "EQUITY"},
        {"symbol": "NEWUSDT", "onboardDate": now, "underlyingType": "COIN"}]})
    dm._fetch_onboard_map()
    assert dm._equity_syms == {"AMGNUSDT"} and set(dm._onboard_map) == {"AMGNUSDT", "NEWUSDT"}


# ── ③·N4 Newly 목록 대상 ──────────────────────────────────────────────
def test_newly_rows_exclude_equity_include_day0(dm):
    _listed(dm, "S250USDT", 5)
    _listed(dm, "S251USDT", 5)                             # 주식
    _listed(dm, "S252USDT", 0, hours=5)                    # 상장 5시간 — 수정 전 제외
    _listed(dm, "S253USDT", 30)
    _listed(dm, "S254USDT", 31)
    dm._equity_syms = {"S251USDT"}
    rows = {r[0] for r in dm.get_newlisted_rows()}
    assert rows == {"S250USDT", "S252USDT", "S253USDT"}


# ── ① 갱신 대상 추가 ───────────────────────────────────────────────────
def test_refresh_targets_add_newly_outside_top100(dm):
    _listed(dm, "S250USDT", 3)
    _listed(dm, "S251USDT", 3)
    _listed(dm, "S5USDT", 3)                               # 이미 상위 100 — 중복 없음
    dm._equity_syms = {"S251USDT"}
    t = [x.symbol for x in dm._refresh_targets(100)]
    assert len(t) == 101 and t[-1] == "S250USDT" and t.count("S5USDT") == 1 and "S251USDT" not in t
    assert dm._newly_syms == {"S250USDT"}
    assert dm._ind_fresh("S250USDT") and not dm._ind_fresh("S251USDT")


def test_stage2_stage3_fetch_newly_symbols(dm):
    _listed(dm, "S250USDT", 3)
    dm._sorted_tickers = dm._sorted_tickers[:1] + [dm._tkr_map["S250USDT"]]
    calls = []
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: calls.append(("ls", s)))
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.0, 0.0))
    dm._client.fetch_all_premium_index = lambda: []
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: calls.append(("k", s)) or [])
    dm._refresh_topn_scores(1)
    dm._refresh_topn_klines(1)
    assert ("ls", "S250USDT") in calls and ("k", "S250USDT") in calls   # 수정 전: 상위 n만 조회


# ── 점수 함수: N1·N2 실제 지표만 · N3 자격 미달 제외 · N5 OI 1시간 · ② 롱 방향만 가점 ───────────
def _row(dm, sym, days, chg):
    _listed(dm, sym, days)
    return (sym, days, "─", "#888888", f"  {chg:+.2f}%", "#00ff00", f"{chg:+.2f}%", "#00ff00", "⟳", "#ffff00", 4)


def _put(dm, sym, **kw):
    ind = dict(dm._simple_ind(dm._tkr_map[sym]), vss=2.5, oi_change_1h=6.0, oi_change=0.0, funding_rate=0.01,
               _data_ready=True)
    ind.update(kw)
    dm._ind_cache[sym] = ind


def test_n1_default_and_stale_not_scored(dm):
    r_def = _row(dm, "S250USDT", 5, 12.0)                  # 갱신 대상 밖 — 기본값(캐시 없음)
    r_old = _row(dm, "S260USDT", 5, 12.0)                  # 옛 캐시 (갱신 대상 밖)
    dm._ind_cache["S260USDT"] = dict(dm._simple_ind(dm._tkr_map["S260USDT"]), vss=4.5, oi_change_1h=12.0,
                                     funding_rate=0.12, _data_ready=True)
    dm._equity_syms = {"S260USDT"}                         # 주식 → 추가 갱신 대상 아님 → 옛 값
    dm._refresh_targets(100)
    assert NewlistedScorer.calc_score("S250USDT", r_def)["ready"] is False
    res = NewlistedScorer.calc_score("S260USDT", r_old)
    assert res["ready"] is False and res["qualified"] is False   # 수정 전: 옛 값으로 자격·1위
    assert NewlistedScorer.get_sorted([r_def, r_old]) == []


def test_n1_newly_refresh_target_scored(dm):
    r = _row(dm, "S250USDT", 5, 12.0)
    dm._refresh_targets(100)                               # 신규 상장 → 갱신 대상
    _put(dm, "S250USDT")
    res = NewlistedScorer.calc_score("S250USDT", r)
    assert res["ready"] and res["qualified"] and res["scores"] == {"surge": 2, "oi": 1, "velocity": 2, "funding": 0}
    assert NewlistedScorer.get_sorted([r]) == [r]


def test_n3_unqualified_rows_excluded(dm):
    a, b = _row(dm, "S250USDT", 5, 12.0), _row(dm, "S251USDT", 3, 25.0)
    dm._refresh_targets(100)
    _put(dm, "S250USDT")
    _put(dm, "S251USDT", vss=1.0, oi_change_1h=1.0)        # 자격 미달 (VSS<1.2 & OI 1h<3)
    assert NewlistedScorer.calc_score("S251USDT", b)["qualified"] is False
    assert NewlistedScorer.get_sorted([b, a]) == [a]       # 수정 전: [a, b] (b '⚠ 자격 미달' 표시)


def test_n4_day0_scored_and_listed(dm):
    r = _row(dm, "S250USDT", 0, 40.0)
    dm._refresh_targets(100)
    _put(dm, "S250USDT", vss=5.0)
    res = NewlistedScorer.calc_score("S250USDT", r)
    assert res["age_weight"] == 2.0 and NewlistedScorer.get_sorted([r]) == [r]   # 수정 전: 0일 제외


@pytest.mark.parametrize("oi10, oi1h, s_oi, qualified", [
    (25.0, 0.0, 0, False),     # 10분 값 무시 (수정 전: |25| → 3점·자격)
    (0.0, -12.0, 0, False),    # OI 감소 — 가점·자격 없음 (수정 전: |−12| → 2점)
    (0.0, 3.0, 0, True),       # 1h +3% → 자격 (VSS 1.0이어도)
    (0.0, 10.0, 2, True),
])
def test_n5_oi_1h_increase_only(dm, oi10, oi1h, s_oi, qualified):
    r = _row(dm, "S250USDT", 5, 0.0)
    dm._refresh_targets(100)
    _put(dm, "S250USDT", vss=1.0, oi_change=oi10, oi_change_1h=oi1h)
    res = NewlistedScorer.calc_score("S250USDT", r)
    assert res["scores"]["oi"] == s_oi and res["qualified"] is qualified


@pytest.mark.parametrize("chg, vel", [(25.0, 3), (-25.0, 0), (12.0, 2), (-12.0, 0), (5.0, 1), (-5.0, 0)])
def test_decision2_velocity_long_direction_only(dm, chg, vel):
    r = _row(dm, "S250USDT", 5, chg)
    dm._refresh_targets(100)
    _put(dm, "S250USDT")
    assert NewlistedScorer.calc_score("S250USDT", r)["scores"]["velocity"] == vel   # 수정 전: 하락도 같은 점수


# ── 1열·3열 표시 ────────────────────────────────────────────────────
def test_col1_day0_text_and_age_labels():
    import middle.widget.panel_col1 as pc1
    src = inspect.getsource(pc1)
    assert "🆕 상장 24시간 이내" in src
    assert 'f"D+{days}  Recent"' not in src and 'f"D+{days}  Mature"' not in src
    assert "⚠ 자격 미달 (VSS/OI 부족)" not in src


def test_col3_withheld_message_and_lifecycle_gate():
    import middle.widget.panel_col3 as pc3
    src = inspect.getsource(pc3)
    assert "⚠ Newly Listed 채점 보류 (갱신 대상 밖·데이터 준비 중)" in src
    assert "if _nl_days > 0 and bars_ready(sym):" in src
    assert "_lc_res = lifecycle_summary(_days, ind) if bars_ready(sym) else None" in src


# ── N7·N8 라이프사이클 ───────────────────────────────────────────────
def test_n7_lifecycle_uses_1h_oi_and_stage3_high_24h(dm):
    from middle.analysis.newlisted_lifecycle import lifecycle_summary, NewlistedLifecycle
    ind = {"vss": 1.0, "oi_change": 0.0, "oi_change_1h": 9.0, "price_change_pct": 5.0, "high_24h_pct": 0.0}
    assert lifecycle_summary(5, ind)[0] == "pre_pump_late"   # 1h OI > 8 (10분 값 0) — 수정 전: 10분 값으로 판정
    assert "_atr_ready" in dm_mod._STAGE3_FIELDS and "high_24h_pct" in dm_mod._STAGE3_FIELDS
    # STAGE3가 시세로 high_24h_pct 기록 (상세 갱신과 같은 식)
    t = SymbolTicker("S0USDT", 100.0, 0.0, 40.0, 1e9, 115.0, 80.0)
    dm._tkr_map["S0USDT"] = t
    dm._sorted_tickers = [t]
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: _bars_ok(tf, limit - 1))
    dm._refresh_topn_klines(1)
    assert dm._ind_cache["S0USDT"]["high_24h_pct"] == 15.0
    assert "stable" not in inspect.getsource(NewlistedLifecycle)   # N8: 도달 불가 90일 단계 삭제


def _bars_ok(tf, n):
    from middle.models import OHLCVBar
    s = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[tf]
    return [OHLCVBar(i * s, 1.0, 1.05, 0.95, 1.0, 100.0, 100.0, i * s + s - 1) for i in range(n)]
