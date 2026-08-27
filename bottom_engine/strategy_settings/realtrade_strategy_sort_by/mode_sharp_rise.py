from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ② 급등 모드 — 강한 상승 흐름. 롱 전용, B등급+, EMA 거시 필수
CONFIG = ModeConfig(
    direction_bias    = "long_only",
    k_long_max        = 40.0,
    k_short_min       = 999.0,
    quality_grade_req = "B",
    volume_mult       = None,
    atr_min           = 0.3,
    atr_max           = 8.0,
    requires_swing    = False,
    macro_ema         = True,
)
