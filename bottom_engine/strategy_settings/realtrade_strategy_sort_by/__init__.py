from __future__ import annotations

from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_config_base import ModeConfig
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_24h_ticker import CONFIG as _CFG_24H
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_sharp_rise import CONFIG as _CFG_RISE
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_sharp_decline import CONFIG as _CFG_DECLINE
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_volatility import CONFIG as _CFG_VOLATILITY
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_4tf_optim import CONFIG as _CFG_4TF
from bottom_engine.strategy_settings.realtrade_strategy_sort_by.mode_newly_listed import CONFIG as _CFG_NEWLY

MODE_CONFIG: dict[str, ModeConfig] = {
    "24h Ticker":       _CFG_24H,
    "Sharp rise":       _CFG_RISE,
    "Sharp decline":    _CFG_DECLINE,
    "Volatility":       _CFG_VOLATILITY,
    "4TF Optimization": _CFG_4TF,
    "Newly Listed":     _CFG_NEWLY,
}

_DEFAULT_CONFIG = MODE_CONFIG["24h Ticker"]


def get_mode_config(sort_mode: str) -> ModeConfig:
    return MODE_CONFIG.get(sort_mode, _DEFAULT_CONFIG)
