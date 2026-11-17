"""
middle/col1_ranking/ranking/pending_listing.py
Sort by: Pending Listing — PENDING_TRADING 상장 예정 심볼 감지 및 분류

MiddleDataManager.fetch_pending_listings()가 조회한 PENDING_TRADING 심볼·markPrice 원본을
PendingEntry 목록으로 변환하고, 유형 배지·남은 시간 표시값을 만든다.

컬럼 레이아웃: # | 심볼 [유형배지] | 상장예정일시(KST) | 남은시간 | markPrice
2026-11-16 수정: 예정일 경과·예정일 미상 표시(P1) · 유형 배지 underlyingType 기준(P4) · 종목별 파싱 오류 격리(P6) ·
  남은 시간 정수 계산·1분 미만·N일 Nh(P7)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from middle.data.data_manager import _EQUITY_TYPES   # 주식·ETF underlyingType (Pending 제외 기준과 같은 정의)


@dataclass
class PendingEntry:
    """PENDING_TRADING 상장 예정 심볼 데이터."""
    symbol:          str
    base_asset:      str
    onboard_date:    int          # Unix ms — 상장 예정 시각
    underlying_type: str          # COIN / EQUITY·HK/KR/CN_EQUITY / COMMODITY / PREMARKET / INDEX / FX
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
        for s, mark in raw:
            try:   # P6: 종목별 격리 — 한 종목 형식 오류가 뒤 종목을 잘라내지 않음
                mp = float(mark.get("markPrice", 0) or 0) if mark else 0.0
                result.append(PendingEntry(
                    symbol=s["symbol"],
                    base_asset=s.get("baseAsset", ""),
                    onboard_date=int(s.get("onboardDate") or 0),
                    underlying_type=s.get("underlyingType") or "COIN",
                    underlying_sub=list(s.get("underlyingSubType") or []),
                    mark_price=mp,
                ))
            except (KeyError, TypeError, ValueError) as e:
                logging.warning("PendingListingDetector.parse %s: %s", s.get("symbol", "?") if isinstance(s, dict) else s, e)
        return result

    @staticmethod
    def get_type_badge(entry: PendingEntry) -> tuple[str, str]:
        """유형 배지 텍스트·색상 반환.

        Returns:
            (배지 텍스트, 색상 hex)
        """
        ut  = entry.underlying_type
        ust = entry.underlying_sub
        # P4: underlyingType 기준 — 홍콩·중국 주식·TradFi 표시 없는 주식·지수·FX가 [COIN]으로 표시되던 문제
        if ut in _EQUITY_TYPES:
            return "[주식]", "#FFA500"       # ORANGE
        if ut == "COMMODITY":
            return "[원자재]", "#C8A000"
        if ut == "PREMARKET":
            return "[프리마켓]", "#C060FF"
        if ut == "INDEX":
            return "[지수]", "#C8A000"
        if ut == "FX":
            return "[FX]", "#C8A000"
        if "DeFi" in ust:
            return "[DeFi]",   "#4EA1FF"     # ACCENT_BLUE
        return "[COIN]", "#11de93"            # POSITIVE

    @staticmethod
    def format_remaining(onboard_ms: int) -> tuple[str, str]:
        """남은 시간 텍스트·색상 반환.

        Returns:
            (텍스트, 색상 hex)
        """
        if onboard_ms <= 0:
            return "—", "#666666"              # P1: 예정일 미상 (DIM_TEXT)
        diff_ms = onboard_ms - time.time() * 1000
        if diff_ms <= 0:
            # P1: 목록은 조회 시점에 PENDING_TRADING(거래 미개시)인 종목 — 예정일이 지났어도 '상장됨'이 아님
            return "예정일 경과", "#FFA500"   # ORANGE
        total_min = int(diff_ms // 60_000)     # P7: 정수 계산 (부동소수 분 손실 없음)
        if total_min < 1:
            return "1분 미만", "#ff007a"       # NEGATIVE
        if total_min < 60:
            return f"{total_min}분 후", "#ff007a"
        h, m = divmod(total_min, 60)
        if h < 24:
            return f"{h}h {m}m 후", "#FFA500"  # ORANGE
        d, h = divmod(h, 24)
        return f"{d}일 {h}h 후", "#666666"     # DIM_TEXT
