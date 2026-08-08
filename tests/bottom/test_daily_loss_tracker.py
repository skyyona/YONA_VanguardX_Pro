"""
tests/bottom/test_daily_loss_tracker.py
DailyLossTracker 단위 테스트.
"""
from __future__ import annotations

import datetime
import json
import os

import pytest
from zoneinfo import ZoneInfo

import bottom.engine_core.daily_loss_tracker as _dlt_mod
from bottom.engine_core.daily_loss_tracker import DailyLossTracker
from bottom.engine_core.risk_manager import MAX_DAILY_LOSS_PCT, RiskManager


@pytest.fixture()
def isolated(tmp_path):
    """_DATA_FILE을 임시 경로로 치환 — 테스트 종료 후 원복."""
    original = _dlt_mod._DATA_FILE
    _dlt_mod._DATA_FILE = str(tmp_path / "daily_loss.json")
    yield tmp_path
    _dlt_mod._DATA_FILE = original


class TestLossPct:
    def test_same_balance(self, isolated):
        DailyLossTracker.ensure_initialized(1000.0)
        assert DailyLossTracker.loss_pct(1000.0) == pytest.approx(0.0)

    def test_loss(self, isolated):
        DailyLossTracker.ensure_initialized(1000.0)
        assert DailyLossTracker.loss_pct(800.0) == pytest.approx(-20.0)

    def test_profit(self, isolated):
        DailyLossTracker.ensure_initialized(1000.0)
        assert DailyLossTracker.loss_pct(1100.0) == pytest.approx(10.0)

    def test_zero_balance(self, isolated):
        DailyLossTracker.ensure_initialized(1000.0)
        assert DailyLossTracker.loss_pct(0.0) == pytest.approx(-100.0)

    def test_no_today_record(self, isolated):
        yesterday = (datetime.datetime.now(tz=ZoneInfo("Asia/Seoul"))
                     - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        with open(str(isolated / "daily_loss.json"), "w", encoding="utf-8") as f:
            json.dump({"date": yesterday, "initial_balance": 1000.0}, f)
        assert DailyLossTracker.loss_pct(800.0) == pytest.approx(0.0)


class TestEnsureInitialized:
    def test_first_call_records_balance(self, isolated):
        DailyLossTracker.ensure_initialized(1234.5)
        with open(str(isolated / "daily_loss.json"), "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["initial_balance"] == 1234.5
        assert "date" in saved

    def test_same_day_recall_does_not_overwrite(self, isolated):
        DailyLossTracker.ensure_initialized(1000.0)
        DailyLossTracker.ensure_initialized(9999.0)
        assert DailyLossTracker.loss_pct(800.0) == pytest.approx(-20.0)


class TestSave:
    def test_save_creates_directory(self, tmp_path):
        original = _dlt_mod._DATA_FILE
        _dlt_mod._DATA_FILE = str(tmp_path / "new_subdir" / "daily_loss.json")
        try:
            result = DailyLossTracker._save({"date": "2026-01-01", "initial_balance": 500.0})
            assert result is True
            assert os.path.exists(_dlt_mod._DATA_FILE)
        finally:
            _dlt_mod._DATA_FILE = original

    def test_save_failure_returns_false(self, tmp_path):
        original = _dlt_mod._DATA_FILE
        new_data_file = str(tmp_path / "daily_loss.json")
        _dlt_mod._DATA_FILE = new_data_file
        os.makedirs(new_data_file)  # _DATA_FILE 경로에 디렉터리 생성 → os.replace() 실패
        try:
            result = DailyLossTracker._save({"date": "2026-01-01"})
            assert result is False
        finally:
            _dlt_mod._DATA_FILE = original


class TestLoad:
    def test_corrupted_json_returns_empty(self, isolated):
        with open(str(isolated / "daily_loss.json"), "w", encoding="utf-8") as f:
            f.write("{ not valid json !!!")
        assert DailyLossTracker._load() == {}

    def test_missing_file_returns_empty(self, isolated):
        assert DailyLossTracker._load() == {}


class TestShouldDailyStop:
    def test_exceeds_limit(self):
        assert RiskManager.should_daily_stop(-(MAX_DAILY_LOSS_PCT + 0.1)) is True

    def test_at_limit_not_triggered(self):
        assert RiskManager.should_daily_stop(-MAX_DAILY_LOSS_PCT) is False
