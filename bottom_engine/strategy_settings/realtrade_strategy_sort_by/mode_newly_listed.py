from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig

# ⑥ 신규 상장 모드 — 롱 전용. 품질·거래량 필터 없음
CONFIG = ModeConfig(
    direction_bias    = "long_only",
    k_long_max        = 30.0,
    k_short_min       = 999.0,
    quality_grade_req = None,
    volume_mult       = None,
    atr_min           = 1.25,
    atr_max           = 15.0,
    requires_swing    = False,
    macro_ema         = False,
)
