"""
tests/middle/test_kline_5m_limit.py
klines 요청 봉 수(_KLINES_LIMITS: 1m·3m·5m·15m·1h 200 / 4h·1d 80) — STAGE3·_refresh_detail·get_ohlcv 세 경로 동일,
지표가 전체 봉(199·79)으로 계산되는지, 두 경로 캐시 봉 수가 같은지 + VWAP·5m ATR% 기존 창 유지.
네트워크 무의존: 시세·파생 서비스만 대역으로 교체하고 실제 갱신 함수를 실행.
klines 대역은 요청 limit에서 미완성 봉 1개를 뺀 수만큼 마감 봉을 돌려준다(ohlcv_data._parse_klines 동작).
"""
import math
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from middle.col2_chart_indicators.mtf_stochrsi import StochRSI
from middle.analysis.atr_percent import AtrPercent
from middle.col3_analysis_panels.technical_analysis.vwap import VWAP
from middle.col3_analysis_panels.technical_analysis.ema_alignment import EMAAlignment
from middle.data import data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.models import OHLCVBar, SymbolTicker

_TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


_PHASE = 21   # 199봉 끝이 진동 중간 — 5m K: 59봉 47.49 / 79봉 41.88 / 199봉 42.66 (창 길이에 따라 구분됨)


def _bars(tf: str, n: int) -> list[OHLCVBar]:
    """완만한 상승 + 다중 주기 진동 — 창 길이에 따라 StochRSI K·VWAP가 달라지도록 구성."""
    step, out = _TF_MS[tf], []
    for i in range(n):
        x = i + _PHASE
        c = (100.0 + 0.05 * i + 3.0 * math.sin(x / 6.0) + 1.5 * math.sin(x / 17.0)
             + 0.8 * math.sin(x / 2.3))
        o = c - 0.3 * math.cos(x / 3.0)
        h = max(o, c) + 0.4 + 0.1 * (i % 4)
        lo = min(o, c) - 0.4 - 0.1 * (i % 3)
        v = 1000.0 + 50.0 * (i % 7)
        out.append(OHLCVBar(i * step, o, h, lo, c, v, v * c, i * step + step - 1))
    return out


class _Klines:
    def __init__(self):
        self.limits: dict[str, int] = {}

    def fetch(self, symbol, interval, limit=None):
        self.limits[interval] = limit
        return _bars(interval, limit - 1)


def _make_dm() -> tuple[MiddleDataManager, _Klines]:
    dm = MiddleDataManager()
    kl = _Klines()
    dm._ohlcv_svc = kl
    dm._fr_svc = types.SimpleNamespace(fetch=lambda symbol: None)
    dm._ls_svc = types.SimpleNamespace(fetch=lambda symbol, period="5m": None)
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda symbol, period="5m": (0.0, 0.0))
    return dm, kl


_LIMITS = {"1m": 200, "3m": 200, "5m": 200, "15m": 200, "1h": 200, "4h": 80, "1d": 80}


def test_detail_requests_limit_table():
    """_refresh_detail: 1m·3m·5m·15m·1h 200, 4h·1d 80."""
    dm, kl = _make_dm()
    dm._refresh_detail("BTCUSDT")
    assert dm_mod._KLINES_LIMITS == _LIMITS
    assert kl.limits == _LIMITS


def test_detail_vwap_atr5m_keep_previous_79_bar_window_and_tf5_uses_all():
    """_refresh_detail: VWAP·5m ATR%는 최근 79봉(기존 창), tf5 StochRSI는 199봉 전체."""
    dm, _ = _make_dm()
    dm._refresh_detail("BTCUSDT")
    ind, b5m = dm._ind_cache["BTCUSDT"], _bars("5m", 199)
    win = b5m[-dm_mod._VWAP_ATR5M_BARS_DETAIL:]
    assert ind["atr_pct_5m"] == AtrPercent.calculate(win)
    assert ind["vwap"] == VWAP.calculate(win).label
    # VWAP는 창 전체 합산 → 199봉 전체였다면 달라짐 (ATR%는 Wilder 수렴으로 창 길이에 둔감해 판별용 부적합)
    assert ind["vwap"] != VWAP.calculate(b5m).label
    assert ind["tf5"]["k"] == StochRSI.calculate_with_series(b5m)[0].k
    assert ind["tf5"]["k"] != StochRSI.calculate_with_series(win)[0].k   # 기존 79봉이었다면 달라짐


def test_stage3_requests_same_limits_as_detail():
    """STAGE3: _refresh_detail과 같은 봉 수 (기존 15m 60 vs 80 경합 제거)."""
    dm, kl = _make_dm()
    dm._sorted_tickers = [SymbolTicker("BTCUSDT", 130.0, 1.0, 1.0, 1e9, 131.0, 99.0)]
    dm._refresh_topn_klines(1)
    assert kl.limits == _LIMITS


def test_both_paths_cache_same_bar_counts_and_indicators_use_all_bars():
    """두 경로가 같은 TF 캐시를 같은 봉 수(199·4h·1d 79)로 덮어씀 — 15m·1h 지표가 경로와 무관하게 같은 값."""
    dm, _ = _make_dm()
    dm._sorted_tickers = [SymbolTicker("ETHUSDT", 130.0, 1.0, 1.0, 1e9, 131.0, 99.0)]
    dm._refresh_topn_klines(1)
    stage3_lens = {tf: len(b) for tf, b in dm._ohlcv_cache["ETHUSDT"].items()}
    stage3_tf15, stage3_tf1h = dm._ind_cache["ETHUSDT"]["tf15"]["k"], dm._ind_cache["ETHUSDT"]["tf1h"]["k"]
    dm._refresh_detail("ETHUSDT")
    detail_lens = {tf: len(b) for tf, b in dm._ohlcv_cache["ETHUSDT"].items()}
    assert stage3_lens == detail_lens == {tf: n - 1 for tf, n in _LIMITS.items()}
    ind = dm._ind_cache["ETHUSDT"]
    assert ind["tf15"]["k"] == stage3_tf15 == StochRSI.calculate_with_series(_bars("15m", 199))[0].k
    assert ind["tf15"]["k"] != StochRSI.calculate_with_series(_bars("15m", 199)[-59:])[0].k   # 기존 STAGE3 59봉이었다면 달라짐
    assert ind["tf1h"]["k"] == stage3_tf1h == StochRSI.calculate_with_series(_bars("1h", 199))[0].k
    b1h = _bars("1h", 199)                                    # 1h EMA50(G_ema) — 199봉 전체로 계산
    assert ind["e50"] == EMAAlignment.calculate(b1h).ema50
    assert ind["e50"] != EMAAlignment.calculate(b1h[-79:]).ema50                  # 79봉이었다면 달라짐


def test_get_ohlcv_fallback_uses_limit_table_no_short_cache():
    """get_ohlcv: 캐시 없을 때 같은 봉 수로 받아 캐시 — 차트(n=60)·엔진 15m(n=19) 호출이 짧은 목록을 남기지 않음."""
    for tf, n in (("1h", 60), ("15m", 19), ("1d", 60), ("1m", 60)):
        dm, kl = _make_dm()
        out = dm.get_ohlcv("SOLUSDT", tf, n)
        assert kl.limits == {tf: _LIMITS[tf]}
        assert len(dm._ohlcv_cache["SOLUSDT"][tf]) == _LIMITS[tf] - 1
        assert len(out) == n


def test_stage3_vwap_atr5m_keep_previous_59_bar_window_and_tf5_uses_all():
    """STAGE3: VWAP·5m ATR%는 최근 59봉(기존 창), tf5 StochRSI는 199봉 전체."""
    dm, _ = _make_dm()
    dm._sorted_tickers = [SymbolTicker("BTCUSDT", 130.0, 1.0, 1.0, 1e9, 131.0, 99.0)]
    dm._refresh_topn_klines(1)
    ind, b5m = dm._ind_cache["BTCUSDT"], _bars("5m", 199)
    win = b5m[-dm_mod._VWAP_ATR5M_BARS_TOPN:]
    assert ind["atr_pct_5m"] == AtrPercent.calculate(win)
    assert ind["vwap"] == VWAP.calculate(win).label
    assert ind["vwap"] != VWAP.calculate(b5m).label
    assert ind["tf5"]["k"] == StochRSI.calculate_with_series(b5m)[0].k
    assert ind["tf5"]["k"] != StochRSI.calculate_with_series(win)[0].k    # 기존 59봉이었다면 달라짐
