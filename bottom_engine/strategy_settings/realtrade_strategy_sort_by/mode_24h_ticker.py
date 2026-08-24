"""
mode_24h_ticker — 24h 거래량 기준 정렬 (표준 모드)

[적용 대상]
  변동성 급등 구간 전용 모드. 24h 거래량 정렬이 후보 심볼을 제공하며,
  실제 진입은 ATR 임계값(1h ATR ≥ 1.80%)을 초과하는 구간에서만 발생한다.

[ATR 임계값 구조 — G4·G8 두 게이트가 독립적으로 동일한 벽을 형성]
  G4 (long/short_condition.py):
    _atr_min_eff = max(cfg.atr_min, _sl_used / 2.0) = max(0.10, 3.6/2.0) = 1.80%
    → 1h ATR < 1.80% 이면 G4에서 직접 차단

  G8 common_liq (prohibition_filter.py):
    liq_long_pct = f(ATR × 2) — 1h ATR 기반 청산 거리 추정값
    → ATR × 2 < sl_used(3.6) → ATR < 1.80% 이면 G8에서도 차단

  두 게이트의 실효 임계값이 수학적으로 동일 (ATR ≥ sl_used / 2):
    G4의 max(atr_min, sl_used/2)는 common_liq 통과 조건에서 역산한 값이다.

[정상 동작 범위]
  대형 저변동성 코인 (BTC·ETH): 1h ATR 중앙값 0.3~0.6% → 상시 차단 (정상)
  고변동성 알트 (DOGE 등): 1h ATR 중앙값 1.3% 수준 → 평상시 차단,
    급등·급락 구간 (ATR > 1.80%) 에서만 진입 — 이것이 의도된 동작이다.

[atr_min = 0.10 해석]
  cfg.atr_min(0.10%)은 정적 하한이나 사실상 비활성.
  런타임 실효 하한은 max(0.10, sl_used/2) — sl_used 변경 시 함께 변동.
  예: sl_used 1.2% → 실효 하한 0.60%
"""
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ① 표준 모드 — 24시간 거래량 기준 정렬. 추가 필터 없음
CONFIG = ModeConfig(
    direction_bias    = "both",
    k_long_max        = 40.0,
    k_short_min       = 60.0,
    quality_grade_req = None,
    volume_mult       = None,
    atr_min           = 0.10,
    atr_max           = 8.0,
    requires_swing    = False,
    macro_ema         = False,
)
