from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeConfig:
    direction_bias:    str         # "both" | "long_only" | "short_only"
    k_long_max:        float       # 롱 진입 허용 최대 K 값 (과매도 확인)
    k_short_min:       float       # 숏 진입 허용 최소 K 값 (과매수 확인)
    quality_grade_req: str | None  # 최소 품질 등급 요건: "A" | "B" | "C" | None
    volume_mult:       float | None  # 거래량 배수 요건 (None = 미적용)
    atr_min:           float       # ATR% 최소 — 너무 정적인 구간 필터
    atr_max:           float       # ATR% 최대 — 과변동 필터
    requires_swing:    bool        # 15m 스윙 고저 구조 확인 여부
    macro_ema:         bool        # EMA5 > EMA50 (롱) / EMA5 < EMA50 (숏) 확인 여부
