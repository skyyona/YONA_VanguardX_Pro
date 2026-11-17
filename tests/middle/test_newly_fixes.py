"""
tests/middle/test_newly_fixes.py
1열 Sort by 'Newly Listed' 결함 수정·사용자 결정 (2026-11-16) — 네트워크 없이 대역.
 ① 신규 상장(30일 이내·주식 제외)을 STAGE2·STAGE3 갱신 대상에 추가 → 실제 지표로 채점
 ③ TradFi 계약(주식·ETF·원자재·FX·상장 전 주식) 목록·추가 갱신 대상 제외 (상장 전 코인은 포함, 2026-11-17)
 N4 상장 24시간 미만(0일) 포함 · N1·N2 실제 봉 지표만 채점 · N3 자격 미달 제외 · N5 OI 1시간
 ② 롱 방향만 가점(가격 상승·OI 증가) · N6 3열 채점 보류 · N7 생애주기 1h OI·STAGE3 고점 대비 % · N8 도달 불가 코드 삭제
 N-1 (2026-11-17) 자격·생애주기 = FR 수신 시각 기준(fr_ready) — 롱숏 미수신은 무관, STAGE2가 멈춘 옛 FR·OI는 제외
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


# ── ③ TradFi 계약 판정 (exchangeInfo contractType — 2026-11-17 주식·ETF → TradFi 전체) ────────
_EI = {"symbols": [   # 실측 exchangeInfo 형식 (2026-11-17)
    {"symbol": "AMGNUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "EQUITY"},
    {"symbol": "HKXUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "HK_EQUITY"},
    {"symbol": "XAUUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "COMMODITY"},      # 원자재
    {"symbol": "EURUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "FX"},             # FX
    {"symbol": "ANTHROPICUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "PREMARKET"},  # 상장 전 주식
    {"symbol": "PREDICTUSDT", "contractType": "PERPETUAL", "underlyingType": "PREMARKET"},          # 상장 전 코인 — 포함
    {"symbol": "BTCDOMUSDT", "contractType": "PERPETUAL", "underlyingType": "INDEX"},
    {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "underlyingType": "COIN"}]}


def test_tradfi_set_from_exchange_info():
    assert dm_mod._build_tradfi_set(_EI) == {"AMGNUSDT", "HKXUSDT", "XAUUSDT", "EURUSDT", "ANTHROPICUSDT"}


def test_fetch_onboard_map_also_sets_tradfi(dm):
    now = int(time.time() * 1000)
    dm._client = types.SimpleNamespace(fetch_exchange_info=lambda: {"symbols": [
        dict(s, onboardDate=now) for s in _EI["symbols"]]})
    dm._fetch_onboard_map()
    assert dm._tradfi_syms == {"AMGNUSDT", "HKXUSDT", "XAUUSDT", "EURUSDT", "ANTHROPICUSDT"}
    assert len(dm._onboard_map) == len(_EI["symbols"])


# ── ③·N4 Newly 목록 대상 ──────────────────────────────────────────────
def test_newly_rows_exclude_equity_include_day0(dm):
    _listed(dm, "S250USDT", 5)
    _listed(dm, "S251USDT", 5)                             # 주식
    _listed(dm, "S252USDT", 0, hours=5)                    # 상장 5시간 — 수정 전 제외
    _listed(dm, "S253USDT", 30)
    _listed(dm, "S254USDT", 31)
    dm._tradfi_syms = {"S251USDT"}
    rows = {r[0] for r in dm.get_newlisted_rows()}
    assert rows == {"S250USDT", "S252USDT", "S253USDT"}


# ── ① 갱신 대상 추가 ───────────────────────────────────────────────────
def test_refresh_targets_add_newly_outside_top100(dm):
    _listed(dm, "S250USDT", 3)
    _listed(dm, "S251USDT", 3)
    _listed(dm, "S5USDT", 3)                               # 이미 상위 100 — 중복 없음
    dm._tradfi_syms = {"S251USDT"}
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
               _data_ready=True, _fr_ts=time.time())   # FR 수신 시각 — Newly 자격 조건(fr_ready, N-1)
    ind.update(kw)
    dm._ind_cache[sym] = ind


def test_n1_default_and_stale_not_scored(dm):
    r_def = _row(dm, "S250USDT", 5, 12.0)                  # 갱신 대상 밖 — 기본값(캐시 없음)
    r_old = _row(dm, "S260USDT", 5, 12.0)                  # 옛 캐시 (갱신 대상 밖)
    dm._ind_cache["S260USDT"] = dict(dm._simple_ind(dm._tkr_map["S260USDT"]), vss=4.5, oi_change_1h=12.0,
                                     funding_rate=0.12, _data_ready=True)
    dm._tradfi_syms = {"S260USDT"}                         # TradFi → 추가 갱신 대상 아님 → 옛 값
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
    assert "if _nl_days > 0 and fr_ready(sym):" in src                              # N-1: bars_ready → fr_ready
    assert "_lc_res = lifecycle_summary(_days, ind) if fr_ready(sym) else None" in src


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


# ── 2026-11-17 FR 롱 방향 — 음수(숏 쏠림)만 가점 ─────────────────────────
@pytest.mark.parametrize("fr, pts", [(0.15, 0), (0.10, 0), (0.05, 0), (0.0, 0), (-0.04, 0), (-0.05, 1),
                                     (-0.09, 1), (-0.10, 2), (-0.5, 2)])
def test_fr_long_direction_negative_only(dm, fr, pts):
    r = _row(dm, "S250USDT", 5, 0.0)
    dm._refresh_targets(100)
    _put(dm, "S250USDT", funding_rate=fr)
    res = NewlistedScorer.calc_score("S250USDT", r)
    assert res["scores"]["funding"] == pts and res["fr"] == fr   # 수정 전: |FR| — +0.10(롱 과밀)도 2점


def test_newly_rows_exclude_commodity_fx_preipo_keep_crypto_premarket(dm):
    now = int(time.time() * 1000)
    syms = [s["symbol"] for s in _EI["symbols"]]
    from middle.models import SymbolTicker
    for s in syms:
        t = SymbolTicker(s, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        dm._tickers.append(t); dm._tkr_map[s] = t
    dm._client = types.SimpleNamespace(fetch_exchange_info=lambda: {"symbols": [
        dict(s, onboardDate=now - 5 * _DAY) for s in _EI["symbols"]]})
    dm._fetch_onboard_map()
    for t in dm._tickers:                                   # 기존 대역 종목은 상장 400일 유지
        dm._onboard_map.setdefault(t.symbol, now - 400 * _DAY)
    rows = {r[0] for r in dm.get_newlisted_rows()}
    assert rows == {"PREDICTUSDT", "BTCDOMUSDT", "BTCUSDT"}  # 수정 전: XAU·EUR·ANTHROPIC 포함 (주식만 제외)


# ── N-1 (2026-11-17): Newly 자격 = FR 수신 시각 기준(fr_ready) — 롱숏 미수신은 무관, STAGE2가 멈춘 옛 FR·OI는 제외 ──
def test_n1_fr_ready_gate(dm):
    rows = []
    stale = time.time() - dm_mod._DERIV_FRESH_SEC - 60
    for sym, fr_ts, ls_ts in (("S1USDT", time.time(), 0.0),       # FR 최신 · 롱숏 수신 기록 없음
                              ("S2USDT", stale, stale),            # FR·롱숏 오래됨 (STAGE2 멈춤 — 차단 등)
                              ("S3USDT", time.time(), time.time())):
        _listed(dm, sym, 5)
        _put(dm, sym, vss=1.0, oi_change_1h=6.0, _fr_ts=fr_ts, _ls_ts=ls_ts)   # 자격은 OI 6% 하나로만
        rows.append(dm.get_row(sym))
    assert [dm.fr_ready(s) for s in ("S1USDT", "S2USDT", "S3USDT")] == [True, False, True]
    assert dm.ind_ready("S1USDT") is False                   # 롱숏 미수신 — ind_ready 기준이었다면 잘못 제외됐을 종목
    assert all(dm.bars_ready(s) for s in ("S1USDT", "S2USDT", "S3USDT"))   # 수정 전 기준(bars_ready)은 셋 다 통과
    q = {r[0]: NewlistedScorer.calc_score(r[0], r)["qualified"] for r in rows}
    assert q == {"S1USDT": True, "S2USDT": False, "S3USDT": True}
    assert {r[0] for r in NewlistedScorer.get_sorted(rows)} == {"S1USDT", "S3USDT"}   # 옛 FR·OI 종목 S2 제외
