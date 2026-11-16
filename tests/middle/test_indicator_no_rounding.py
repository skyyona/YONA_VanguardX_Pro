"""
tests/middle/test_indicator_no_rounding.py
엔진 판정 입력 지표 계산 반올림 제거 — 실거래(중단 모듈) 값이 백테스트 계산과 같은 값인지 검증.
StochRSI K·D(G_K·KD 익절·G6·G7.5) / 1h EMA5·EMA50(G_ema) / ATR%(G4·청산 근접) /
청산 근접(G8 common_liq) / 거래량 비율(G5) / 펀딩비(G8 common_fr).
네트워크 무의존: 시세·파생 서비스만 대역으로 교체하고 실제 _refresh_detail 실행.
"""
import math
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from bottom_engine.backtest.backtest_runner import BacktestRunner
from middle.analysis.atr_percent import AtrPercent
from middle.col2_chart_indicators.mtf_stochrsi import StochRSI
from middle.col3_analysis_panels.derivative_analysis.liquidation_proximity import LiquidationProximityPanel
from middle.col3_analysis_panels.technical_analysis.ema_alignment import EMAAlignment
from middle.data.data_manager import MiddleDataManager
from middle.models import FundingRateData, LongShortData, OHLCVBar

_TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _bars(tf: str, n: int, base: float = 100.0) -> list[OHLCVBar]:
    """다중 주기 진동 — K·D·EMA·ATR이 소수 끝자리까지 정수 아닌 값이 되도록 구성. base로 가격대 지정."""
    step, out = _TF_MS[tf], []
    for i in range(n):
        x = i + 21
        c = base * (1.0 + 0.0005 * i + 0.03 * math.sin(x / 6.0) + 0.015 * math.sin(x / 17.0)
                    + 0.008 * math.sin(x / 2.3))
        o = c * (1.0 - 0.003 * math.cos(x / 3.0))
        h = max(o, c) * 1.004
        lo = min(o, c) * 0.996
        v = 1000.0 + 50.0 * (i % 7) + 13.7 * math.sin(x)
        out.append(OHLCVBar(i * step, o, h, lo, c, v, v * c, i * step + step - 1))
    return out


def test_stochrsi_equals_backtest_kd():
    """StochRSI K·D·K 시리즈 = 백테스트 _calc_kd (기존 RSI 4자리·K·D 2자리 반올림 → 최대 0.006 차이)."""
    b = _bars("5m", 199)
    res, k_series = StochRSI.calculate_with_series(b)
    kb, db = BacktestRunner._calc_kd([x.close for x in b], 14, 14, 3, 3)
    assert abs(res.k - kb[-1]) < 1e-9 and abs(res.d - db[-1]) < 1e-9
    assert StochRSI.calculate(b).k == res.k and StochRSI.calculate(b).d == res.d
    assert max(abs(a - c) for a, c in zip(k_series[-len(kb):], kb)) < 1e-9
    assert res.k != round(res.k, 2)                          # 반올림 안 된 값 그대로


def test_ema_equals_backtest_low_price_no_tie():
    """저가 종목(가격 0.0001대) EMA5·EMA50 = 백테스트 _calc_ema_series, 6자리 반올림이면 같아지던 경우도 구분."""
    b = _bars("1h", 199, base=0.00012)
    closes = [x.close for x in b]
    r = EMAAlignment.calculate(b)
    e5b = BacktestRunner._calc_ema_series(closes, 5)[-1]
    e50b = BacktestRunner._calc_ema_series(closes, 50)[-1]
    assert math.isclose(r.ema5, e5b, rel_tol=1e-12) and math.isclose(r.ema50, e50b, rel_tol=1e-12)
    assert round(r.ema5, 6) == round(r.ema50, 6)             # 기존 저장 방식이었다면 같은 값 → G_ema 롱·숏 모두 차단
    assert r.ema5 != r.ema50 and (r.ema5 > r.ema50) == (e5b > e50b)


def test_atr_pct_equals_backtest():
    b = _bars("1h", 199)
    atr_bt = BacktestRunner._calc_atr_series(b, 14)[-1]
    assert abs(AtrPercent.calculate(b) - atr_bt) < 1e-12


def test_liquidation_proximity_unrounded():
    """청산 근접 = 백테스트 common_liq 식 그대로 (기존 2자리 반올림 → liq_safe 경계 판정 0.073% 차이)."""
    atr, fr, lr = 1.84731, 0.0123, 63.7
    liq = LiquidationProximityPanel.estimate(atr, fr, lr)
    base = max(atr * 2.0, 1.0)
    long_dist = max(0.5, min(5.0, base - abs(fr) * 0.3 - (lr - 50.0) / 50.0 * base * 0.5))
    assert liq.liq_long_pct == -long_dist and liq.liq_short_pct == max(0.5, min(5.0, base))
    assert liq.liq_long_pct != round(liq.liq_long_pct, 2)


class _Klines:
    def fetch(self, symbol, interval, limit=None):
        return _bars(interval, limit - 1)


def test_detail_refresh_stores_unrounded_engine_inputs():
    """_refresh_detail 저장값 — atr·e5·e50·volume_ratio·funding_rate·liq·tf5 K·D가 계산값 그대로."""
    dm = MiddleDataManager()
    dm._ohlcv_svc = _Klines()
    dm._fr_svc = types.SimpleNamespace(fetch=lambda symbol: FundingRateData(symbol, 0.000054321, 0))
    dm._ls_svc = types.SimpleNamespace(fetch=lambda symbol, period="5m": LongShortData(symbol, 61.37, 38.63, 1.5887, 0))
    dm._oi_svc = types.SimpleNamespace(fetch_changes=lambda symbol, period="5m": (0.0, 0.0))
    dm._refresh_detail("BTCUSDT")
    ind = dm._ind_cache["BTCUSDT"]
    b1h, b1m, b5m = _bars("1h", 199), _bars("1m", 199), _bars("5m", 199)
    atr = AtrPercent.calculate(b1h)
    ema = EMAAlignment.calculate(b1h)
    assert ind["atr"] == ind["atr_pct"] == atr
    assert (ind["e5"], ind["e50"]) == (ema.ema5, ema.ema50)
    assert ind["volume_ratio"] == b1m[-1].volume / (sum(x.volume for x in b1m[-21:-1]) / 20.0)
    assert ind["funding_rate"] == 0.000054321 * 100.0
    liq = LiquidationProximityPanel.estimate(atr, 0.000054321 * 100.0, 61.37)
    assert (ind["liq_long_pct"], ind["liq_short_pct"]) == (liq.liq_long_pct, liq.liq_short_pct)
    tf5 = StochRSI.calculate(b5m)
    assert (ind["tf5"]["k"], ind["tf5"]["d"]) == (tf5.k, tf5.d)
    assert ind["volume_ratio"] != round(ind["volume_ratio"], 3)
    assert ind["funding_rate"] != round(ind["funding_rate"], 4)
