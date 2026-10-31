"""
middle/col1_ranking_blacklist/ranking/pending_listing.py
Sort by: Pending Listing — PENDING_TRADING 상장 예정 심볼 감지 및 분류

MiddleDataManager.fetch_pending_listings()가 조회한 PENDING_TRADING 심볼·markPrice 원본을
PendingEntry 목록으로 변환하고, 유형 배지·남은 시간 표시값을 만든다.

컬럼 레이아웃: # | 심볼 [유형배지] | 상장예정일시 | 남은시간 | markPrice
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field


@dataclass
class PendingEntry:
    """PENDING_TRADING 상장 예정 심볼 데이터."""
    symbol:          str
    base_asset:      str
    onboard_date:    int          # Unix ms — 상장 예정 시각
    underlying_type: str          # COIN / EQUITY / COMMODITY / PREMARKET
    underlying_sub:  list         # TradFi / DeFi / ...
    mark_price:      float        # markPrice API 조회값 (USDT)


class PendingListingDetector:
    """PENDING_TRADING 상장 예정 심볼 변환·표시값."""

    @staticmethod
    def parse(raw: list[tuple[dict, dict | None]]) -> list[PendingEntry]:
        """PENDING_TRADING 원본 → PendingEntry 목록 (입력 순서 = onboardDate 오름차순 유지).

        Args:
            raw: [(exchangeInfo 심볼 dict, premiumIndex 응답 또는 None), ...]
        Returns:
            PendingEntry 목록 — markPrice 조회 실패 심볼은 0.0
        """
        result: list[PendingEntry] = []
        try:
            for s, mark in raw:
                mp = float(mark.get("markPrice", 0)) if mark else 0.0
                result.append(PendingEntry(
                    symbol=s["symbol"],
                    base_asset=s.get("baseAsset", ""),
                    onboard_date=s.get("onboardDate", 0),
                    underlying_type=s.get("underlyingType", "COIN"),
                    underlying_sub=list(s.get("underlyingSubType", [])),
                    mark_price=mp,
                ))
        except Exception as e:
            logging.warning("PendingListingDetector.parse: %s", e)
        return result

    @staticmethod
    def get_type_badge(entry: PendingEntry) -> tuple[str, str]:
        """유형 배지 텍스트·색상 반환.

        Returns:
            (배지 텍스트, 색상 hex)
        """
        ut  = entry.underlying_type
        ust = entry.underlying_sub
        if ut in ("EQUITY", "KR_EQUITY") and "TradFi" in ust:
            return "[TradFi]", "#FFA500"     # ORANGE
        if ut == "COMMODITY":
            return "[원자재]", "#C8A000"
        if ut == "PREMARKET":
            return "[프리마켓]", "#C060FF"
        if "DeFi" in ust:
            return "[DeFi]",   "#4EA1FF"     # ACCENT_BLUE
        return "[COIN]", "#11de93"            # POSITIVE

    @staticmethod
    def format_remaining(onboard_ms: int) -> tuple[str, str]:
        """남은 시간 텍스트·색상 반환.

        Returns:
            (텍스트, 색상 hex)
        """
        diff_ms = onboard_ms - time.time() * 1000
        if diff_ms <= 0:
            return "상장됨",  "#11de93"       # POSITIVE
        hours = diff_ms / (1000 * 3600)
        if hours < 1:
            return f"{int(diff_ms / 60000)}분 후", "#ff007a"  # NEGATIVE
        if hours < 24:
            h = int(hours)
            m = int((hours - h) * 60)
            return f"{h}h {m}m 후", "#FFA500"  # ORANGE
        days = int(hours / 24)
        return f"{days}일 후", "#666666"        # DIM_TEXT
