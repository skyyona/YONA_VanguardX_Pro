"""
middle/col1_ranking/ranking/volatility_scorer.py
Volatility Sort by — ATR% 변동성 내림차순 정렬
대상: 지금 갱신되는 종목 중 봉 지표가 실제로 들어온 종목만 (bars_ready — 2026-11-16 V1~V3:
거래량 101~200위 기본값 ATR 2.0·갱신 대상 밖 옛 값·시작 직후 기본값이 실제 종목을 밀어내던 문제)
"""
from __future__ import annotations

from middle.widget.shared_context import bars_ready, get_ind


class VolatilityScorer:
    """Volatility 모드: ATR%(변동성) 내림차순 정렬."""

    @staticmethod
    def get_sorted(data: list, limit: int = 100) -> list:
        def _vol_key(r):
            ind = get_ind(r[0])
            if not ind.get("_atr_ready"):
                return 1.0                    # 1h 봉 15개 미만·조회 실패 — ATR 미계산, 맨 아래 '데이터 부족' (V4)
            # bars_ready·_atr_ready 종목은 STAGE3·상세 갱신이 atr를 항상 기록 — 예전 행 5번째 칸(24h 변동률 문자) 예비 경로 삭제 (V7)
            return -ind["atr"]
        sorted_data = sorted((r for r in data if bars_ready(r[0])), key=_vol_key)
        return sorted_data[:limit]
