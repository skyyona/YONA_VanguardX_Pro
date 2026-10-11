"""
bottom_engine/strategy/rsi_divergence.py
RSI 시리즈 계산 + 거래량 확인 유틸.
  calc_rsi_series : Wilder's Smoothed RSI 시리즈 반환 (G2에서 사용)
  _check_volume   : 마지막 봉 거래량 ≥ 최근 20봉 평균 × vol_mult
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
