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
