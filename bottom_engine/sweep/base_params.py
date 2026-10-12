"""
bottom_engine/sweep/base_params.py
스윕 공통 기준 — 전 스윕이 동일 파라미터·동일 심볼을 쓰도록 단일 선언.

기준 파라미터는 실거래 _strategy.json "24h Ticker" 와 일치시킨다.
변경 시 이 파일만 수정하면 전 스윕에 반영된다.
"""
from __future__ import annotations

import json
from pathlib import Path

from bottom_engine.models import StrategyParams, ProhibitionFlags

PERIOD = "90일"

_SYMBOLS_PATH = Path(__file__).resolve().parents[2] / "selected_symbols.json"


def load_symbols() -> list[str]:
    """selected_symbols.json 의 심볼 목록 반환."""
    with open(_SYMBOLS_PATH, encoding="utf-8") as f:
        return list(json.load(f)["symbols"])


def make_base_params() -> StrategyParams:
    """스윕 기준 파라미터 — 실거래 24h Ticker 설정과 동일."""
    p = StrategyParams()
    p.sort_mode         = "24h Ticker"
    p.funds_pct         = 100
    p.leverage          = 20
    p.stop_loss         = 2.9
    p.trail_stop        = 1.2
    p.use_macro         = False
    p.m4_rsi_vol_mult   = 1.5
    p.prohibition       = ProhibitionFlags(
        common_liq    = True,
        common_fr     = True,
        common_new    = True,
        common_hunter = True,
        long_fomo     = True,
        long_short_open  = True,
        short_accum      = True,
        short_long_open  = True,
    )
    return p
