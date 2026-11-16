"""
tests/middle/test_deriv_fetch_fail.py
H 롱숏·FR 조회 실패 값 처리 (2026-11-16, Sharp rise·decline 공용) — 네트워크 없이 대역.
 - 조회 성공 시각(_ls_ts·_fr_ts)이 _DERIV_FRESH_SEC(180초) 이내일 때만 채점 가능(ind_ready)
 - STAGE2 실패: 값·성공 시각 직전 그대로 (한 번도 성공 못 했으면 기본값 50%·0% → 채점 보류)
 - 상세 갱신 실패: 엔진 입력은 기존대로 50%·0% (백테스트 중립값과 같음), 성공 시각 0 → 채점 보류
 - WS 봉 마감 재계산은 REST 조회 시각 기준 (재계산 시각 아님)
"""
import types

import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as ctx
from middle.col1_ranking.ranking.sharp_decline_scorer import SharpDeclineScorer
from middle.col1_ranking.ranking.sharp_rise_scorer import SharpRiseScorer
from middle.col3_analysis_panels.derivative_analysis.liquidation_proximity import LiquidationProximityPanel
from middle.data.data_manager import MiddleDataManager
from middle.models import FundingRateData, LongShortData, OHLCVBar, SymbolTicker

_T0 = 1_800_000_000.0
_STEP = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _bars(tf, n):
    s = _STEP[tf]
    return [OHLCVBar(i * s, 1 + i * 1e-3, 1.01 + i * 1e-3, 0.99 + i * 1e-3, 1 + i * 1e-3, 100.0 + i % 7, 100.0,
                     i * s + s - 1) for i in range(n)]


@pytest.fixture()
def env(monkeypatch):
    now = [_T0]
    monkeypatch.setattr(dm_mod.time, "time", lambda: now[0])
    dm = MiddleDataManager()
    t = SymbolTicker("AUSDT", 1.0, 0.0, 0.0, 1e9, 1.0, 1.0)
    dm._tickers = dm._sorted_tickers = [t]
    dm._tkr_map, dm._vol_rank = {"AUSDT": t}, {"AUSDT": 1}
    dm._client = types.SimpleNamespace(fetch_all_premium_index=lambda: [], fetch_funding_info=lambda: [])
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda s: (0.0, 0.0))
    dm._ohlcv_svc = types.SimpleNamespace(fetch=lambda s, tf, limit=None: _bars(tf, limit - 1))
    monkeypatch.setattr(ctx, "_data_mgr", dm)
    feed = {"ls": None, "fr": None}
    dm._ls_svc = types.SimpleNamespace(fetch=lambda s: feed["ls"])
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: feed["fr"])
    return dm, now, feed


def _ls(long_pct):
    return LongShortData("AUSDT", long_pct, 100 - long_pct, long_pct / (100 - long_pct), 0)


def _fr(rate):
    return FundingRateData("AUSDT", rate, 0)


def _stage2(dm):
    dm._refresh_topn_scores(1)
    dm._ind_cache["AUSDT"]["_data_ready"] = True     # STAGE3 봉 지표 반영 상태


def _qual(sym="AUSDT"):
    return SharpRiseScorer.calc_score(sym)["qualified"], SharpDeclineScorer.calc_score(sym)["qualified"]


def test_stage2_never_succeeded_not_ready(env):
    dm, _, _ = env
    _stage2(dm)                                        # 롱숏·FR 조회 실패
    ind = dm._ind_cache["AUSDT"]
    assert (ind["long_ratio"], ind["funding_rate"], ind["_stage2_ready"]) == (50.0, 0.0, True)   # 값·청산 조건 기존 그대로
    assert dm.ind_ready("AUSDT") is False
    assert _qual() == (False, False)                   # 수정 전: (True, True) — 기본값으로 두 모드 동시 자격


def test_stage2_success_then_failures_keep_value_until_180s(env):
    dm, now, feed = env
    feed.update(ls=_ls(72.0), fr=_fr(0.0006))
    _stage2(dm)
    assert dm.ind_ready("AUSDT") is True and _qual() == (False, True)
    feed.update(ls=None, fr=None)
    for dt in (60.0, 120.0, 180.0):                    # 연속 실패 — 직전 실제 값 유지, 180초까지 채점
        now[0] = _T0 + dt
        _stage2(dm)
        ind = dm._ind_cache["AUSDT"]
        assert (ind["long_ratio"], ind["funding_rate"]) == (72.0, 0.06)
        assert dm.ind_ready("AUSDT") is True
    now[0] = _T0 + 180.5
    assert dm.ind_ready("AUSDT") is False and _qual() == (False, False)
    feed.update(ls=_ls(72.0), fr=_fr(0.0006))          # 다시 성공 → 채점
    _stage2(dm)
    assert dm.ind_ready("AUSDT") is True


def test_each_of_ls_and_fr_required(env):
    dm, _, feed = env
    feed.update(ls=_ls(72.0), fr=None)
    _stage2(dm)
    assert dm.ind_ready("AUSDT") is False              # FR 실제 값 없음 (기본 0%)
    dm._ind_cache.clear()                              # 새 종목 상태에서 반대 경우
    feed.update(ls=None, fr=_fr(0.0006))
    _stage2(dm)
    assert dm.ind_ready("AUSDT") is False              # 롱숏 실제 값 없음 (기본 50%)
    feed.update(ls=_ls(72.0))
    _stage2(dm)
    assert dm.ind_ready("AUSDT") is True


def test_saved_funding_reuse_counts_as_success(env):
    dm, now, feed = env
    feed.update(ls=_ls(72.0), fr=_fr(0.0006))
    last = int(_T0 * 1000) - 600_000
    dm._client.fetch_all_premium_index = lambda: [{"symbol": "AUSDT", "nextFundingTime": last + 3_600_000}]
    dm._client.fetch_funding_info = lambda: [{"symbol": "AUSDT", "fundingIntervalHours": 1}]
    feed["fr"] = FundingRateData("AUSDT", 0.0006, last)
    _stage2(dm)
    calls = []
    dm._fr_svc = types.SimpleNamespace(fetch=lambda s: calls.append(s))   # 다음 정산 전 → 조회 안 함
    now[0] = _T0 + 240.0
    _stage2(dm)
    assert calls == [] and dm._ind_cache["AUSDT"]["_fr_ts"] == _T0 + 240.0
    assert dm.ind_ready("AUSDT") is True


def test_detail_failure_engine_inputs_unchanged_but_not_ready(env):
    dm, _, feed = env
    dm._engine_sym = "AUSDT"
    feed.update(ls=_ls(72.0), fr=_fr(0.0006))
    dm._refresh_detail("AUSDT")
    ind = dm._ind_cache["AUSDT"]
    assert (ind["long_ratio"], ind["funding_rate"]) == (72.0, 0.06)
    assert (ind["_ls_ts"], ind["_fr_ts"]) == (_T0, _T0) and dm.ind_ready("AUSDT") is True
    feed.update(ls=None, fr=None)
    dm._refresh_detail("AUSDT")
    ind = dm._ind_cache["AUSDT"]
    # 엔진 입력: 기존과 같은 중립값 50%·0% + 그 값의 청산 근접 (백테스트 데이터 없는 구간과 같음)
    liq = LiquidationProximityPanel.estimate(ind["atr"], 0.0, 50.0)
    assert (ind["long_ratio"], ind["funding_rate"]) == (50.0, 0.0)
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == (liq.liq_long_pct, liq.liq_short_pct)
    assert (ind["_ls_ts"], ind["_fr_ts"]) == (0.0, 0.0)
    assert dm.ind_ready("AUSDT") is False and _qual() == (False, False)   # 수정 전: (True, True)


def test_ws_recompute_uses_rest_fetch_time(env):
    dm, now, feed = env
    dm._engine_sym = "AUSDT"
    feed.update(ls=_ls(72.0), fr=_fr(0.0006))
    dm._refresh_detail("AUSDT")
    assert dm._deriv_cache["AUSDT"][4] == _T0
    now[0] = _T0 + 300.0                               # 5분 뒤 WS 봉 마감 재계산 — 파생 값은 5분 전 조회분
    dm._compute_detail("AUSDT", dict(dm._ohlcv_cache["AUSDT"]), *dm._deriv_cache["AUSDT"])
    ind = dm._ind_cache["AUSDT"]
    assert (ind["_ls_ts"], ind["_fr_ts"]) == (_T0, _T0)            # 재계산 시각(T0+300) 아님
    assert dm.ind_ready("AUSDT") is False                           # 180초 초과 → 채점 보류
