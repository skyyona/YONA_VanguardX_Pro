"""
bottom/engine_core/sort_mode_config.py
Sort by 6개 모드별 전략 파라미터 정의

각 모드는 4TF 합의 이후 적용할 필터 조건을 정의한다.
direction_bias / K 임계값 / 품질 등급 / 거래량 / ATR 범위 / 스윙 / EMA거시
"""
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


# ── 6개 모드 설정 ─────────────────────────────────────────────────

MODE_CONFIG: dict[str, ModeConfig] = {

    # ① 표준 모드 — 24시간 거래량 기준 정렬. 추가 필터 없음
    "24h Ticker": ModeConfig(
        direction_bias    = "both",
        k_long_max        = 40.0,    # 완화: 35.0 → 40.0 (역사 +5.1%p 기회 확대)
        k_short_min       = 60.0,    # 완화: 65.0 → 60.0 (역사 +6.6%p 기회 확대)
        quality_grade_req = None,
        volume_mult       = None,
        atr_min           = 0.10,    # 정적 하한 (원래 설계값). 실효 하한은 런타임 max(atr_min, sl_used/2) — [Q3]
        atr_max           = 8.0,
        requires_swing    = False,
        macro_ema         = False,
    ),

    # ② 급등 모드 — 강한 상승 흐름. 롱 전용, B등급+, EMA 거시 필수
    #    (requires_swing: 완화 — 스윙 구조 미적용)
    "Sharp rise": ModeConfig(
        direction_bias    = "long_only",
        k_long_max        = 35.0,    # 완화: 30.0 → 35.0 (역사 +5.1%p 기회 확대)
        k_short_min       = 999.0,   # 숏 불가 (실질 차단)
        quality_grade_req = "B",
        volume_mult       = None,    # 완화: 1.5 → None (vol_ratio 평균 0.65x 대응)
        atr_min           = 0.3,     # 완화: 0.5 → 0.3 (bull≥3 통과 심볼 ATR 분포 반영)
        atr_max           = 8.0,
        requires_swing    = False,   # 완화: True → False
        macro_ema         = True,    # 수정: False → True (Sharp decline 대칭)
    ),

    # ③ 급락 모드 — 강한 하락 흐름. 숏 전용, B등급+, EMA 거시 필수
    #    (requires_swing: 완화 — 스윙 구조 미적용)
    "Sharp decline": ModeConfig(
        direction_bias    = "short_only",
        k_long_max        = -999.0,  # 롱 불가 (실질 차단)
        k_short_min       = 65.0,    # 완화: 70.0 → 65.0 (역사 +6.6%p 기회 확대)
        quality_grade_req = "B",
        volume_mult       = None,    # 완화: 1.5 → None (vol_ratio 평균 0.65x 대응)
        atr_min           = 1.25,    # sl_used=2.5% 기준 최소 ATR 정합
        atr_max           = 8.0,
        requires_swing    = False,
        macro_ema         = True,
    ),

    # ④ 변동성 모드 — 고변동성 단기. 양방향, A등급
    "Volatility": ModeConfig(
        direction_bias    = "both",
        k_long_max        = 30.0,    # 완화: 25.0 → 30.0 (역사 발생률 현실화)
        k_short_min       = 70.0,    # 완화: 75.0 → 70.0 (숏 기회 확대)
        quality_grade_req = "A",
        volume_mult       = 1.5,     # 완화: 2.0 → 1.5 (진입 기회 확대)
        atr_min           = 0.7,     # 완화: 1.0 → 0.7 (ATR≥1.0 심볼 부재 해소)
        atr_max           = 8.0,
        requires_swing    = False,
        macro_ema         = False,
    ),

    # ⑤ 4TF 최적화 모드 — 최고 품질. 양방향, A등급, 모든 구조 필터 활성
    "4TF Optimization": ModeConfig(
        direction_bias    = "both",
        k_long_max        = 35.0,    # 완화: 30.0 → 35.0 (역사 +5.1%p 기회 확대)
        k_short_min       = 65.0,    # 완화: 70.0 → 65.0 (역사 +6.6%p 기회 확대)
        quality_grade_req = "A",
        volume_mult       = None,    # 완화: 1.5 → None (vol_ratio 평균 0.65x 대응)
        atr_min           = 1.85,    # sl_used=3.7%(4.0% clamp) 기준 최소 ATR 정합
        atr_max           = 6.0,
        requires_swing    = False,
        macro_ema         = False,
    ),

    # ⑥ 신규 상장 모드 — 롱 전용. 품질·거래량 필터 없음 (신규 데이터 부족 대응)
    "Newly Listed": ModeConfig(
        direction_bias    = "long_only",
        k_long_max        = 30.0,    # 완화: 20.0 → 30.0 (역사 17~27% 구간)
        k_short_min       = 999.0,   # 숏 불가
        quality_grade_req = None,
        volume_mult       = None,
        atr_min           = 1.25,    # sl_used=2.5% 기준 최소 ATR 정합
        atr_max           = 15.0,
        requires_swing    = False,
        macro_ema         = False,
    ),
}

# 알 수 없는 모드에 대한 fallback
_DEFAULT_CONFIG = MODE_CONFIG["24h Ticker"]


def get_mode_config(sort_mode: str) -> ModeConfig:
    return MODE_CONFIG.get(sort_mode, _DEFAULT_CONFIG)
