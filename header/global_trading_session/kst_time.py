"""KST 현재 시간 문자열 생성"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from core.config import KST_TIMEZONE


class KstTime:
    def __init__(self) -> None:
        self._tz = ZoneInfo(KST_TIMEZONE)

    def now(self) -> datetime:
        return datetime.now(self._tz)

    def label(self) -> str:
        now = self.now()
        period = "AM" if now.hour < 12 else "PM"
        return now.strftime(f"%Y-%m-%d {period} %I:%M:%S KST")
