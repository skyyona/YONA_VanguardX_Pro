"""장 구분 — 아시아·유럽·미국 세션 감지"""
from __future__ import annotations
from datetime import time


class SessionClassifier:
    @staticmethod
    def classify(now_time: time) -> str:
        active = []
        if SessionClassifier._in_range(now_time, time(9, 0),  time(18, 0)):
            active.append("Asia")
        if SessionClassifier._in_range(now_time, time(17, 0), time(2, 0)):
            active.append("Europe")
        if SessionClassifier._in_range(now_time, time(22, 0), time(7, 0)):
            active.append("US")
        if not active:
            return "No Active Session"
        return " + ".join(active) + " Session Active"

    @staticmethod
    def _in_range(now_t: time, start_t: time, end_t: time) -> bool:
        if start_t <= end_t:
            return start_t <= now_t < end_t
        return now_t >= start_t or now_t < end_t
