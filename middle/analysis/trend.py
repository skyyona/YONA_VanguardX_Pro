"""
middle/analysis/trend.py
일일 추세(1h·4h·1d)·단기 추세(1m·3m·5m·15m) 단일 정의 — TF별 StochRSI 방향(K−D ≥ 2 ▲ / ≤ −2 ▼ / 그 외 ↔) 다수결.
1열 4TF Optimization 점수·Gold 1위·2열 MACRO TREND·4TF COMPLETE ALIGNMENT·3열 4TF 종합분석 공용.
"""
from __future__ import annotations

from dataclasses import dataclass

DAILY_KEYS = ("tf1h", "tf4h", "tf1d")
SHORT_KEYS = ("tf1", "tf3", "tf5", "tf15")
DAILY_MIN  = 2   # 일일 추세: 3TF 중 같은 방향 2개 이상
SHORT_MIN  = 3   # 단기 추세: 4TF 중 같은 방향 3개 이상


@dataclass(frozen=True)
class Trend:
    direction: str | None   # "▲" | "▼" | None(중립 — 같은 방향이 기준 개수 미만)
    count:     int          # 방향이 있으면 그 방향 TF 수, 중립이면 ▲·▼ 중 많은 쪽 수
    total:     int          # 대상 TF 수 (일일 3 / 단기 4)
    up:        int
    down:      int


def _trend(ind: dict, keys: tuple[str, ...], need: int) -> Trend:
    dirs = [ind.get(k, {}).get("dir", "↔") for k in keys]
    up, down = dirs.count("▲"), dirs.count("▼")
    if up >= need:
        return Trend("▲", up, len(keys), up, down)
    if down >= need:
        return Trend("▼", down, len(keys), up, down)
    return Trend(None, max(up, down), len(keys), up, down)


def daily_trend(ind: dict) -> Trend:
    """일일 추세 — 1h·4h·1d 중 같은 방향 2개 이상."""
    return _trend(ind, DAILY_KEYS, DAILY_MIN)


def short_trend(ind: dict) -> Trend:
    """단기 추세 — 1m·3m·5m·15m 중 같은 방향 3개 이상."""
    return _trend(ind, SHORT_KEYS, SHORT_MIN)


def trend_text(t: Trend) -> str:
    """표시 문구 — 예: '▲ 2/3', '↔ 중립'."""
    return f"{t.direction} {t.count}/{t.total}" if t.direction else "↔ 중립"
