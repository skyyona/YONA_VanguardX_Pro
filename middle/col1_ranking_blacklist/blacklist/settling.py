"""
middle/col1_ranking_blacklist/settling.py
Settling 심볼 감지 — 랭킹 1열 상단 별도 표시용
Binance exchangeInfo status 기반 결제 진행 중 심볼 필터
"""
from __future__ import annotations

from dataclasses import dataclass

# Binance 비정상 거래 상태 코드
_SETTLING_STATUSES = frozenset({
    "SETTLING", "BREAK", "END_OF_DAY",
    "PRE_DELIVERING", "DELIVERING", "DELIVERED",
})


@dataclass
class SettlingEntry:
    symbol:    str
    status:    str     # Binance status code
    label:     str     # 표시 레이블 ("SETTLING", "HALT" 등)
    color_hint: str    # "settling" | "halt" | "warning"


class SettlingDetector:
    """Binance exchangeInfo 기반 Settling 심볼 감지."""

    @classmethod
    def detect(cls, exchange_info: dict) -> list[SettlingEntry]:
        """exchangeInfo 응답에서 Settling 상태 USDT 심볼 목록 반환."""
        result: list[SettlingEntry] = []
        for sym_info in exchange_info.get("symbols", []):
            symbol = sym_info.get("symbol", "")
            status = sym_info.get("status", "TRADING")
            if not symbol.endswith("USDT"):
                continue
            if status in _SETTLING_STATUSES:
                result.append(SettlingEntry(
                    symbol=symbol,
                    status=status,
                    label=cls._label(status),
                    color_hint=cls._color_hint(status),
                ))
        return sorted(result, key=lambda e: e.symbol)

    @staticmethod
    def _label(status: str) -> str:
        mapping = {
            "SETTLING":         "SETTLING",
            "BREAK":            "HALT",
            "END_OF_DAY":       "EOD",
            "PRE_DELIVERING":   "DELISTING",
            "DELIVERING":       "DELISTING",
            "DELIVERED":        "DELISTED",
        }
        return mapping.get(status, status)

    @staticmethod
    def _color_hint(status: str) -> str:
        if status in ("SETTLING", "END_OF_DAY"):
            return "settling"
        if status == "BREAK":
            return "halt"
        return "warning"

