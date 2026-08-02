"""
middle/col3_analysis_panels/player_detection/energy_balance.py
에너지 균형 (롱/숏) 계산 — Player Detection 패널 하단 분할 바
_calc_energy() + _energy_status() 로직 대응

가중 합산:
  BPR(매수압박) 50% + RSI 1h 25% + VWAP 위치 15% + StochRSI K(1h) 10%
"""
from __future__ import annotations

from dataclasses import dataclass

from middle.widget.constants import (
    POSITIVE as _POSITIVE, NEGATIVE as _NEGATIVE, ORANGE as _ORANGE,
    YELLOW as _YELLOW, LIGHT_GREEN as _LGR,
)
_LIGHT_GREEN = _LGR


@dataclass
class EnergyBalanceResult:
    long_ratio:  float   # 롱 에너지 비율 (0.0~1.0)
    long_pct:    int     # 롱 에너지 % (정수)
    short_pct:   int     # 숏 에너지 %
    status_text: str     # 상태 메시지
    status_color: str    # 상태 색상


class EnergyBalance:
    """에너지 균형 계산기.

    _calc_energy(ind) + _energy_status(long_ratio) 로직 그대로 대응.
    각 입력은 해당 전문 모듈에서 계산된 값을 받음.
    """

    @staticmethod
    def calculate(
        bpr:           float = 0.5,    # BPR.from_candles() 또는 BPR.from_taker_ratio()
        rsi_1h:        float = 50.0,   # RSI.calculate(bars_1h)
        vwap_above:    bool  = False,  # VWAP.calculate().position == "above"
        stochrsi_k_1h: float = 50.0,  # StochRSI.calculate(bars_1h).k
    ) -> EnergyBalanceResult:
        """롱/숏 에너지 균형 계산.

        Args:
            bpr:           매수 압박 비율 (0~1)
            rsi_1h:        1시간봉 RSI (0~100)
            vwap_above:    현재가가 VWAP 위에 있는지 여부
            stochrsi_k_1h: 1시간봉 StochRSI K (0~100)
        """
        raw = (
            bpr                   * 0.50 +
            (rsi_1h / 100.0)      * 0.25 +
            (0.15 if vwap_above else 0.0) +
            (stochrsi_k_1h / 100.0) * 0.10
        )
        long_ratio = max(0.05, min(0.95, raw))
        long_pct   = int(long_ratio * 100)
        short_pct  = 100 - long_pct

        status_text, status_color = EnergyBalance._classify(long_pct)

        return EnergyBalanceResult(
            long_ratio=round(long_ratio, 4),
            long_pct=long_pct,
            short_pct=short_pct,
            status_text=status_text,
            status_color=status_color,
        )

    @staticmethod
    def _classify(long_pct: int) -> tuple[str, str]:
        """_energy_status() 로직 대응."""
        if long_pct >= 70:
            return "🔥 강한 상승 에너지 — 롱 에너지 최고조", _POSITIVE
        if long_pct >= 58:
            return "▲ 롱 에너지 우세 — 롱 엔진 진입 검토", _LIGHT_GREEN
        if long_pct >= 45:
            return "─ 에너지 균형 — 방향 확정 후 엔진 선택", _YELLOW
        if long_pct >= 32:
            return "▼ 숏 에너지 우세 — 숏 엔진 진입 검토", _ORANGE
        return "❄ 강한 하락 에너지 — 숏 에너지 최고조", _NEGATIVE

