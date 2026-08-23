from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ④ 변동성 모드 — 고변동성 단기. 양방향, A등급
CONFIG = ModeConfig(
    direction_bias    = "both",
    k_long_max        = 30.0,
    k_short_min       = 70.0,
    quality_grade_req = "A",
    volume_mult       = 1.5,
    atr_min           = 0.7,
    atr_max           = 8.0,
    requires_swing    = False,
    macro_ema         = False,
)
