"""장 구분 — 아시아·유럽·미국 세션 감지"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ_ASIA   = ZoneInfo("Asia/Tokyo")
_TZ_EUROPE = ZoneInfo("Europe/London")
_TZ_US     = ZoneInfo("America/New_York")


class SessionClassifier:
    @staticmethod
    def classify(now_kst: datetime) -> str:
        active = []
        if 9 <= now_kst.astimezone(_TZ_ASIA).hour < 18:
            active.append("Asia")
        if 8 <= now_kst.astimezone(_TZ_EUROPE).hour < 17:
            active.append("Europe")
        if 8 <= now_kst.astimezone(_TZ_US).hour < 17:
            active.append("US")
        return " + ".join(active) + " Session Active" if active else "No Active Session"
