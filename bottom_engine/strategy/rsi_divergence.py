"""
bottom_engine/strategy/rsi_divergence.py
RSI 과매도/과매수 반전 신호 + 거래량 확인 — 실거래·백테스트 공용 계산 유틸.

사용:
  from bottom_engine.strategy.rsi_divergence import detect_rsi_divergence

인자 closes/volumes 길이 ≥ lookback + rsi_period + 5 필요.
반환: (rsi_div_bull: bool, rsi_div_bear: bool, vol_ok: bool)
  rsi_div_bull : lookback 내 RSI 최저값 < oversold_th AND 현재 RSI ≥ 최저값 + rsi_min_diff (과매도 반전)
  rsi_div_bear : lookback 내 RSI 최고값 > overbought_th AND 현재 RSI ≤ 최고값 - rsi_min_diff (과매수 반전)
  vol_ok       : 마지막 봉 거래량 ≥ 최근 20봉 평균 × vol_mult
"""
from __future__ import annotations


def calc_rsi_series(closes: list[float], period: int = 14) -> list[float]:
    """Wilder's Smoothed RSI 시리즈.

    반환 길이 = len(closes) - period - 1.
    첫 period개 봉은 웜업이므로 결과에 포함되지 않음.
    """
    if len(closes) <= period:
        return []
    gains:  list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0.0 else 0.0)
        losses.append(-d if d < 0.0 else 0.0)
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsi_list: list[float] = []
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0.0:
            rsi_list.append(100.0)
        else:
            rs = avg_g / avg_l
            rsi_list.append(100.0 - 100.0 / (1.0 + rs))
    return rsi_list


def detect_rsi_divergence(
    closes:         list[float],
    volumes:        list[float],
    lookback:       int   = 20,
    price_min_diff: float = 0.5,    # 미사용 — 하위 호환성 유지
    rsi_min_diff:   float = 3.0,    # 반전 강도 임계값 (현재 RSI와 최저/최고값 간 최소 차이)
    vol_mult:       float = 1.5,
    rsi_period:     int   = 14,
    oversold_th:    float = 35.0,   # 롱: lookback 내 RSI 최저값이 이 값 미만이어야 함
    overbought_th:  float = 65.0,   # 숏: lookback 내 RSI 최고값이 이 값 초과이어야 함
) -> tuple[bool, bool, bool]:
    """RSI 과매도/과매수 반전 신호 탐지 + 거래량 확인.

    closes, volumes : 시간 오름차순 (인덱스 0 = 가장 오래된 봉)
    반환 : (rsi_div_bull, rsi_div_bear, vol_ok)
    """
    needed = lookback + rsi_period + 5
    if len(closes) < needed or len(volumes) < needed:
        return False, False, False

    # RSI 계산 창: 마지막 (lookback + rsi_period + 2) 봉 사용
    win_size = lookback + rsi_period + 2
    win_cls  = closes[-win_size:]
    rsi_full = calc_rsi_series(win_cls, rsi_period)
    if len(rsi_full) < lookback:
        return False, False, False

    rsi_lb  = rsi_full[-lookback:]
    rsi_cur = rsi_lb[-1]

    rsi_min = min(rsi_lb)
    rsi_max = max(rsi_lb)

    # 불리시: lookback 내 RSI가 과매도 구간 진입 후 rsi_min_diff 이상 반등
    rsi_div_bull = (rsi_min < oversold_th) and (rsi_cur >= rsi_min + rsi_min_diff)
    # 베어리시: lookback 내 RSI가 과매수 구간 진입 후 rsi_min_diff 이상 하락
    rsi_div_bear = (rsi_max > overbought_th) and (rsi_cur <= rsi_max - rsi_min_diff)
    vol_ok       = _check_volume(volumes, vol_mult)

    return rsi_div_bull, rsi_div_bear, vol_ok


def _check_volume(volumes: list[float], vol_mult: float) -> bool:
    """마지막 봉 거래량 ≥ 최근 20봉 평균 × vol_mult."""
    if vol_mult <= 0.0:
        return True
    n = min(21, len(volumes))
    if n < 2:
        return True
    avg_vol = sum(volumes[-n:-1]) / (n - 1)
    if avg_vol <= 0.0:
        return True
    return volumes[-1] >= avg_vol * vol_mult
