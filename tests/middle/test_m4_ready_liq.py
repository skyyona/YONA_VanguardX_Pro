"""
tests/middle/test_m4_ready_liq.py
④ 10-29 항목 (2026-11-05):
 ④-1 1열 M4 준비 = 엔진 M4Entry G2(15m 마감 봉 19개 RSI 50)·G7.5(1열 Sort by와 같은 이름 모드의 use_macro)
 ④-2 갱신 대상(거래량 상위 100) 밖 행은 "─ 데이터 없음" (대상 안 미계산은 "─ 로딩중")
 ④-3 STAGE2·STAGE3 반영된 갱신 대상 행은 실제 청산 근접도 (상세 경로와 같은 함수·입력)
실제 STAGE2·STAGE3 함수 실행, 네트워크 조회만 대역.
"""
import pytest

import middle.data.data_manager as dm_mod
import middle.widget.shared_context as _ctx
from middle.data.data_manager import MiddleDataManager
from middle.models import OHLCVBar, SymbolTicker, FundingRateData, LongShortData
from middle.col3_analysis_panels.derivative_analysis.liquidation_proximity import LiquidationProximityPanel
from middle.analysis.atr_percent import AtrPercent
from bottom_engine.models import StrategyParams
from bottom_engine.strategy.rsi_divergence import calc_rsi_series

_TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _bars(tf, closes):
    step = _TF_MS[tf]
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append(OHLCVBar(i * step, o, max(o, c) * 1.002, min(o, c) * 0.998, c, 100.0 + i % 7, 1000.0, (i + 1) * step - 1))
    return out


def _wave(n, drift):
    """drift>0 상승(RSI>50), drift<0 하락(RSI<50) — 등락이 섞인 결정적 수열."""
    p, out = 100.0, []
    for i in range(n):
        p *= 1 + drift + (0.004 if i % 3 == 0 else -0.003)
        out.append(round(p, 6))
    return out


def _tkr(sym, vol):
    return SymbolTicker(sym, 100.0, 1.0, 1.0, vol, 101.0, 99.0)


def _dm(monkeypatch, use_macro_by_mode=None):
    use_macro_by_mode = use_macro_by_mode or {}
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default",
                        staticmethod(lambda m: StrategyParams(sort_mode=m, use_macro=use_macro_by_mode.get(m, True))))
    return MiddleDataManager()


def _put(dm, sym, closes15, macro_kd=(50.0, 50.0), rank=1):
    dm._ind_cache[sym] = {tf: {"k": macro_kd[0], "d": macro_kd[1]} for tf in ("tf1h", "tf4h", "tf1d")}
    dm._ohlcv_cache[sym] = {"15m": _bars("15m", closes15)}
    dm._vol_rank[sym] = rank


def _m4(dm, sym, use_macro):
    return dm._make_row(_tkr(sym, 1.0), use_macro)[2]


# ── ④-1 G2 ───────────────────────────────────────────────────
def test_g2_follows_engine_rsi50_not_stochrsi(monkeypatch):
    dm = _dm(monkeypatch)
    for sym, drift in (("UPUSDT", 0.003), ("DNUSDT", -0.003)):
        closes = _wave(199, drift)
        _put(dm, sym, closes)
        rsi = calc_rsi_series(closes[-19:], period=14)[-1]
        assert (rsi > 50) == (drift > 0)
        assert _m4(dm, sym, use_macro=False) == ("▲ 롱 대기" if rsi > 50 else "▼ 숏 대기")


def test_g2_input_is_same_cache_slice_engine_reads(monkeypatch):
    """엔진 G2 입력(shared_context.generate_ohlcv(sym, 19, '15m') 종가)과 1열 계산 입력이 같은 19봉."""
    dm = _dm(monkeypatch)
    closes = _wave(199, 0.001)
    _put(dm, "XUSDT", closes)
    monkeypatch.setattr(_ctx, "_data_mgr", dm)
    eng = [b["c"] for b in _ctx.generate_ohlcv("XUSDT", 19, "15m")]
    assert eng == [b.close for b in dm._ohlcv_cache["XUSDT"]["15m"][-19:]]
    eng_rsi = calc_rsi_series(eng, period=14)[-1]
    assert _m4(dm, "XUSDT", False) == ("▲ 롱 대기" if eng_rsi > 50 else "▼ 숏 대기")


def test_g2_rsi_exactly_50_both_sides_pass(monkeypatch):
    dm = _dm(monkeypatch)
    # 마지막 19봉: 첫 14번 등락 = 상승 7·하락 7 (같은 폭) → 평균 상승=평균 하락, 이후 4봉 보합 → 같은 비율 감소 → RSI 정확히 50
    tail = [100.0 + (i % 2) for i in range(15)] + [100.0] * 4   # 15번째 종가 100 뒤 보합
    closes = _wave(180, 0.001) + tail
    _put(dm, "FLATUSDT", closes)
    assert calc_rsi_series(closes[-19:], period=14)[-1] == 50.0
    assert _m4(dm, "FLATUSDT", True) == "↔ 중립"


# ── ④-1 G7.5 (use_macro) ─────────────────────────────────────
def test_macro_block_only_when_use_macro(monkeypatch):
    dm = _dm(monkeypatch)
    _put(dm, "UPUSDT", _wave(199, 0.003), macro_kd=(30.0, 40.0))     # 거시 −3 → 롱 차단 조건
    _put(dm, "DNUSDT", _wave(199, -0.003), macro_kd=(60.0, 50.0))    # 거시 +3 → 숏 차단 조건
    assert _m4(dm, "UPUSDT", True) == "▲ 거시차단" and _m4(dm, "UPUSDT", False) == "▲ 롱 대기"
    assert _m4(dm, "DNUSDT", True) == "▼ 거시차단" and _m4(dm, "DNUSDT", False) == "▼ 숏 대기"


def test_sort_mode_selects_same_name_mode_use_macro(monkeypatch):
    dm = _dm(monkeypatch, {"Sharp rise": True, "24h Ticker": False})
    _put(dm, "UPUSDT", _wave(199, 0.003), macro_kd=(30.0, 40.0))
    dm._tickers = dm._sorted_tickers = [_tkr("UPUSDT", 1.0)]
    assert dm._sort_mode == "24h Ticker"
    assert dm.get_all_ranked_by_change(10)[0][2] == "▲ 롱 대기"      # 24h Ticker: use_macro False
    dm.set_sort_mode("Sharp rise")
    assert dm.get_ranking_rows()[0][2] == "▲ 거시차단"               # 모드 변경 즉시 풀 재생성
    dm.set_sort_mode("24h Ticker")
    assert dm.get_ranking_rows()[0][2] == "▲ 롱 대기"


# ── ④-2 데이터 없음 / 로딩중 ─────────────────────────────────
def test_out_of_refresh_range_shows_no_data(monkeypatch):
    dm = _dm(monkeypatch)
    dm._vol_rank.update({"INUSDT": 100, "OUTUSDT": 101})
    assert _m4(dm, "INUSDT", True) == "─ 로딩중"        # 갱신 대상, STAGE3 전
    assert _m4(dm, "OUTUSDT", True) == "─ 데이터 없음"  # 갱신 대상 밖 — 계산 안 함
    assert _m4(dm, "NORANKUSDT", True) == "─ 데이터 없음"
    dm._ind_cache["OUTUSDT"] = {"tf15": {"k": 80.0, "d": 20.0}}   # 지표는 있어도 15m 봉 없으면 판정 불가
    assert _m4(dm, "OUTUSDT", True) == "─ 데이터 없음"


# ── ④-3 청산 근접도 (실제 STAGE2·STAGE3 실행) ─────────────────
class _OHLCV:
    def fetch(self, sym, tf, limit):
        return _bars(tf, _wave(limit - 1, 0.001))


class _FR:
    def fetch(self, sym):
        return FundingRateData(sym, 0.0005, 0)          # 0.05%


class _LS:
    def fetch(self, sym):
        return LongShortData(sym, 70.0, 30.0, 70 / 30, 0)


class _OI:
    def fetch_changes(self, sym):
        return 1.5, 0.0


class _Client:   # STAGE2 정산 시각 조회 대역 — 빈 응답 = 펀딩비 매 주기 조회(기존 동작)
    def fetch_all_premium_index(self):
        return []

    def fetch_funding_info(self):
        return []


def _stage_dm(monkeypatch, syms, engine_sym=""):
    dm = _dm(monkeypatch)
    dm._client = _Client()
    dm._ohlcv_svc, dm._fr_svc, dm._ls_svc, dm._oi_svc = _OHLCV(), _FR(), _LS(), _OI()
    dm._sorted_tickers = [_tkr(s, 1e9 - i) for i, s in enumerate(syms)]
    dm._engine_sym = engine_sym
    return dm


def _expected_liq(dm, sym):
    atr = AtrPercent.calculate(_OHLCV().fetch(sym, "1h", dm_mod._KLINES_LIMITS["1h"]))
    liq = LiquidationProximityPanel.estimate(atr, 0.05, 70.0)
    return liq.liq_long_pct, liq.liq_short_pct


@pytest.mark.parametrize("order", ["stage2_first", "stage3_first"])
def test_liq_uses_real_values_after_both_stages(monkeypatch, order):
    dm = _stage_dm(monkeypatch, ["AUSDT"])
    first, second = ((dm._refresh_topn_scores, dm._refresh_topn_klines) if order == "stage2_first"
                     else (dm._refresh_topn_klines, dm._refresh_topn_scores))
    first(1)
    ind = dm._ind_cache["AUSDT"]
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == (-2.0, 2.0)   # 한 단계만 반영 — 기본값 유지
    second(1)
    ind = dm._ind_cache["AUSDT"]
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == _expected_liq(dm, "AUSDT")
    assert ind["liq_long_pct"] != -2.0


def test_liq_matches_detail_path_formula(monkeypatch):
    """목록 행 값 = 상세 경로(_compute_detail)와 같은 함수·입력 (ATR% 1h·FR%·롱 비율)."""
    dm = _stage_dm(monkeypatch, ["AUSDT"])
    dm._refresh_topn_scores(1)
    dm._refresh_topn_klines(1)
    ind = dm._ind_cache["AUSDT"]
    liq = LiquidationProximityPanel.estimate(ind["atr_pct"], ind["funding_rate"], ind["long_ratio"])
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == (liq.liq_long_pct, liq.liq_short_pct)


def test_engine_symbol_liq_untouched_by_stage2(monkeypatch):
    dm = _stage_dm(monkeypatch, ["ENGUSDT"], engine_sym="ENGUSDT")
    dm._ind_cache["ENGUSDT"] = {"_data_ready": True, "atr_pct": 3.0, "funding_rate": 0.0,
                                "long_ratio": 50.0, "liq_long_pct": -4.2, "liq_short_pct": 4.2}
    dm._refresh_topn_scores(1)
    ind = dm._ind_cache["ENGUSDT"]
    assert ind["long_ratio"] == 70.0                                    # STAGE2 필드는 갱신
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == (-4.2, 4.2)   # 엔진 입력 청산 값 불변
