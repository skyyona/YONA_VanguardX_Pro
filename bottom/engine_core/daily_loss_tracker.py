"""bottom/engine_core/daily_loss_tracker.py — KST 기준 일일 실현 손실 추적기.

walletBalance(실현 손익 전용)를 이용해 KST 자정 기준 당일 손실율을 계산한다.
data/daily_loss.json 에 영속화하여 앱 재시작 시에도 당일 누적 손실이 유지된다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import KST_TIMEZONE

_KST = ZoneInfo(KST_TIMEZONE)
_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "daily_loss.json",
)


class DailyLossTracker:
    """KST 자정 기준 당일 실현 잔고 변화율 추적 — data/daily_loss.json 영속화."""

    @staticmethod
    def _today() -> str:
        return datetime.now(tz=_KST).strftime("%Y-%m-%d")

    @staticmethod
    def _load() -> dict:
        try:
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}

    @staticmethod
    def _save(data: dict) -> bool:
        try:
            os.makedirs(os.path.dirname(_DATA_FILE), exist_ok=True)
            tmp = _DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, _DATA_FILE)
            return True
        except OSError:
            return False

    @classmethod
    def ensure_initialized(cls, current_balance: float) -> None:
        """KST 자정을 넘기면 당일 초기 잔고를 새로 기록한다.

        날짜가 바뀌지 않았으면 아무것도 하지 않는다.
        """
        today = cls._today()
        data  = cls._load()
        if data.get("date") != today:
            cls._save({"date": today, "initial_balance": current_balance})

    @classmethod
    def loss_pct(cls, current_balance: float) -> float:
        """당일 실현 손실 비율 (%). 손실 시 음수, 이익 시 양수.

        data/daily_loss.json 에 오늘 날짜 데이터가 없으면 0.0 반환.
        """
        today = cls._today()
        data  = cls._load()
        if data.get("date") != today:
            return 0.0
        initial = data.get("initial_balance", 0.0)
        if initial <= 0:
            return 0.0
        return (current_balance - initial) / initial * 100.0
