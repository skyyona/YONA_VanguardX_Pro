"""
bottom_engine/strategy/energy_exhaustion.py
ENERGY 진입 판정 — BPR 에너지 소멸 + 1m Stoch RSI 트리거.

에너지 소멸 판정식:
  bear_exhausted (롱 허가): bpr_prev <= 0.40 AND bpr_cur >= 0.52
  bull_exhausted (숏 허가): bpr_prev >= 0.60 AND bpr_cur <= 0.48

1m Stoch RSI 트리거:
  롱: prev_K <= 20 < cur_K
  숏: prev_K >= 80 > cur_K

허가 유효 시간: 다음 5m봉 갱신까지, 그 안에서 첫 트리거 1회만.
BPR 정의: (close - low) / (high - low), 5m × 3봉 평균.
"""
from __future__ import annotations

_BPR_PERIOD = 3  # 5m × 3봉 평균

_BEAR_EXHAUST_PREV = 0.40
_BEAR_EXHAUST_CUR  = 0.52
_BULL_EXHAUST_PREV = 0.60
_BULL_EXHAUST_CUR  = 0.48

_K_LONG_TRIGGER  = 20.0
_K_SHORT_TRIGGER = 80.0


def _bpr_avg(bars: list, period: int) -> float:
    """최근 period봉 BPR 평균 계산."""
    recent = bars[-period:] if len(bars) >= period else bars
    if not recent:
        return 0.5
    total = 0.0
    for b in recent:
        rng = b.high - b.low
        total += (b.close - b.low) / rng if rng > 0 else 0.5
    return round(total / len(recent), 4)


class EnergyExhaustion:
    """BPR 에너지 소멸 + 1m Stoch RSI 트리거 판정 — ENERGY entry_variant 전용."""

    @staticmethod
    def check_exhaustion(bars_5m_recent: list) -> tuple[bool, bool]:
        """5m 봉 슬라이스로 에너지 소멸 판정.

        Parameters
        ----------
        bars_5m_recent : 최소 6봉 이상 (이전 3봉 포함)

        Returns
        -------
        (bear_exhausted, bull_exhausted)
        """
        need = _BPR_PERIOD * 2
        if len(bars_5m_recent) < need:
            return False, False
        bpr_prev = _bpr_avg(bars_5m_recent[:-_BPR_PERIOD], _BPR_PERIOD)
        bpr_cur  = _bpr_avg(bars_5m_recent,                 _BPR_PERIOD)
        bear_ex  = (bpr_prev <= _BEAR_EXHAUST_PREV) and (bpr_cur >= _BEAR_EXHAUST_CUR)
        bull_ex  = (bpr_prev >= _BULL_EXHAUST_PREV) and (bpr_cur <= _BULL_EXHAUST_CUR)
        return bear_ex, bull_ex

    @staticmethod
    def check_trigger(prev_k: float, cur_k: float, side: str) -> bool:
        """1m Stoch RSI K 값으로 트리거 판정.

        side: "long" | "short"
        롱: prev_K <= 20 < cur_K
        숏: prev_K >= 80 > cur_K
        """
        if side == "long":
            return prev_k <= _K_LONG_TRIGGER < cur_k
        return prev_k >= _K_SHORT_TRIGGER > cur_k
