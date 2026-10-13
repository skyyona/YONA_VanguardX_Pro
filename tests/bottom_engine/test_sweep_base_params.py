"""
tests/bottom_engine/test_sweep_base_params.py
스윕 기준 파라미터 = _strategy.json 동기화 검증. mock 라이브러리 미사용.
"""
from dataclasses import asdict

import pytest

import bottom_engine.strategy_settings.strategy_loader as _sl
from bottom_engine.strategy_settings.strategy_loader import StrategyLoader
from bottom_engine.sweep import base_params as bp


def test_make_base_params_equals_strategy_json():
    assert asdict(bp.make_base_params()) == asdict(StrategyLoader.load("24h Ticker"))


def test_make_base_params_returns_new_object_each_call():
    a = bp.make_base_params()
    b = bp.make_base_params()
    a.stop_loss = 99.0
    assert a is not b and b.stop_loss != 99.0


def test_missing_mode_raises(tmp_path):
    empty = tmp_path / "_strategy.json"
    empty.write_text("{}", encoding="utf-8")
    orig = _sl._STRATEGY_PATH
    _sl._STRATEGY_PATH = empty
    try:
        with pytest.raises(RuntimeError):
            bp.make_base_params()
    finally:
        _sl._STRATEGY_PATH = orig


def test_run_metadata_has_commit_and_params():
    p = bp.make_base_params()
    meta = bp.run_metadata(p, "90일", ["BTCUSDT", "ETHUSDT"])
    assert meta["commit"] and meta["commit"] != ""
    assert meta["params"]["stop_loss"] == p.stop_loss
    assert meta["symbols_count"] == 2 and meta["period"] == "90일"
