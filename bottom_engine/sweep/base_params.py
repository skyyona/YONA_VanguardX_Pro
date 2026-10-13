"""
bottom_engine/sweep/base_params.py
스윕 공통 기준 — 전 스윕이 동일 파라미터·동일 심볼을 쓰도록 단일 선언.

기준 파라미터는 _strategy.json "24h Ticker" 를 직접 읽는다.
파라미터 변경 시 _strategy.json 만 수정하면 전 스윕에 자동 반영된다.
base_params.py 는 수정하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from bottom_engine.models import StrategyParams
from bottom_engine.strategy_settings.strategy_loader import StrategyLoader

PERIOD = "90일"

_SYMBOLS_PATH = Path(__file__).resolve().parents[2] / "selected_symbols.json"


def load_symbols() -> list[str]:
    """selected_symbols.json 의 심볼 목록 반환."""
    with open(_SYMBOLS_PATH, encoding="utf-8") as f:
        return list(json.load(f)["symbols"])


def make_base_params() -> StrategyParams:
    """스윕 기준 파라미터 — _strategy.json '24h Ticker' 를 직접 읽어 자동 동기화."""
    return StrategyLoader.load("24h Ticker")
