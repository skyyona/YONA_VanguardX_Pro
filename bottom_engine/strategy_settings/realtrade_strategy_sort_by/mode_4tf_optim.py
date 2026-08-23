from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ⑤ 4TF 최적화 모드 — 최고 품질. 양방향, A등급, 모든 구조 필터 활성
CONFIG = ModeConfig(
    direction_bias    = "both",
    k_long_max        = 35.0,
    k_short_min       = 65.0,
    quality_grade_req = "A",
    volume_mult       = None,
    atr_min           = 1.85,
    atr_max           = 6.0,
    requires_swing    = False,
    macro_ema         = False,
)
