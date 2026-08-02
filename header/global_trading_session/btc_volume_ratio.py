"""BTC 거래량 비율 — 현재 시간봉 / 7일 동일 시간대 평균"""
from __future__ import annotations
from header.api.binance_client import HeaderBinanceClient


class BtcVolumeRatio:
    def __init__(self, client: HeaderBinanceClient) -> None:
        self._client = client

    def fetch(self) -> tuple[str, str]:
        """(volume_label, volume_hint) 반환"""
        ratio = self._client.fetch_btc_volume_ratio()
        return self._build_label(ratio)

    @staticmethod
    def _build_label(ratio: float) -> tuple[str, str]:
        pct  = int(round((ratio - 1.0) * 100))
        sign = "+" if pct >= 0 else ""
        if ratio >= 1.5:
            return f"매우 활발 ({sign}{pct}%)", "very_high"
        if ratio >= 1.3:
            return f"보통 이상 ({sign}{pct}%)", "high"
        if ratio >= 0.7:
            return f"보통 ({sign}{pct}%)", "normal"
        return f"보통 이하 ({sign}{pct}%)", "low"
