from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ③ 급락 모드 — 강한 하락 흐름. 숏 전용, B등급+, EMA 거시 필수
CONFIG = ModeConfig(
    direction_bias    = "short_only",
    k_long_max        = -999.0,
    k_short_min       = 65.0,
    quality_grade_req = "B",
    volume_mult       = None,
    atr_min           = 1.25,
    atr_max           = 8.0,
    requires_swing    = False,
    macro_ema         = True,
)
