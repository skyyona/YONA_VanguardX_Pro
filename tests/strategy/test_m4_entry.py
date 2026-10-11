"""
tests/strategy/test_m4_entry.py
M4Entry.evaluate() + DivergenceDetector.detect() 단위 테스트.
mock/patch/MagicMock 사용 없음. 순수 함수 입력→출력 검증.
"""
import pytest
from bottom_engine.strategy.m4_entry import M4Entry
from bottom_engine.models import StrategyParams
from middle.col2_chart_indicators.divergence_detector import DivergenceDetector
from middle.models import OHLCVBar


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────

def _params(sort_mode: str = "24h Ticker") -> StrategyParams:
    return StrategyParams(sort_mode=sort_mode)


def _bar(low: float, high: float) -> OHLCVBar:
    mid = (low + high) / 2.0
    return OHLCVBar(open_time=0, open=mid, high=high, low=low,
                    close=mid, volume=100.0, quote_volume=mid * 100.0,
                    close_time=0)


# ── TestG1Long ─────────────────────────────────────────────────────────────

class TestG1Long:
    """G1 롱 — 불리시 다이버전스 단독 검증 (ablation=1)."""

    def _eval(self, ind: dict) -> tuple:
        return M4Entry.evaluate("long", ind, _params(), ablation=1)

    def test_bull_div_ok(self):
        ok, _ = self._eval({"rsi_div_bull": True})
        assert ok is True

    def test_no_bull_div_blocked(self):
        ok, reason = self._eval({"rsi_div_bull": False})
        assert ok is False
        assert "G1" in reason
        assert "불리시" in reason

    def test_missing_key_defaults_false(self):
        ok, reason = self._eval({})
        assert ok is False
        assert "G1" in reason


# ── TestG1Short ────────────────────────────────────────────────────────────

class TestG1Short:
    """G1 숏 — 베어리시 다이버전스 단독 검증 (ablation=1)."""

    def _eval(self, ind: dict) -> tuple:
        return M4Entry.evaluate("short", ind, _params(), ablation=1)

    def test_bear_div_ok(self):
        ok, _ = self._eval({"rsi_div_bear": True})
        assert ok is True

    def test_no_bear_div_blocked(self):
        ok, reason = self._eval({"rsi_div_bear": False})
        assert ok is False
        assert "G1" in reason
        assert "베어리시" in reason

    def test_missing_key_defaults_false(self):
        ok, reason = self._eval({})
        assert ok is False
        assert "G1" in reason


# ── TestG1VolumeCheck ──────────────────────────────────────────────────────

class TestG1VolumeCheck:
    """G1 거래량 체크 (ablation=2) 격리 검증."""

    def test_long_vol_ok(self):
        ok, _ = M4Entry.evaluate(
            "long", {"rsi_div_bull": True, "rsi_div_vol_ok": True},
            _params(), ablation=2)
        assert ok is True

    def test_long_vol_fail_blocked(self):
        ok, reason = M4Entry.evaluate(
            "long", {"rsi_div_bull": True, "rsi_div_vol_ok": False},
            _params(), ablation=2)
        assert ok is False
        assert "거래량 미확인" in reason

    def test_short_vol_fail_blocked(self):
        ok, reason = M4Entry.evaluate(
            "short", {"rsi_div_bear": True, "rsi_div_vol_ok": False},
            _params(), ablation=2)
        assert ok is False
        assert "거래량 미확인" in reason

    def test_ablation1_skips_vol_check(self):
        # ablation=1: rsi_div_vol_ok=False여도 거래량 게이트 비활성
        ok, _ = M4Entry.evaluate(
            "long", {"rsi_div_bull": True, "rsi_div_vol_ok": False},
            _params(), ablation=1)
        assert ok is True


# ── TestG2Direction ────────────────────────────────────────────────────────

class TestG2Direction:
    """G2 15m RSI 방향 확인 (ablation=3) 격리 검증."""

    _LONG = {"rsi_div_bull": True, "rsi_div_vol_ok": True}
    _SHORT = {"rsi_div_bear": True, "rsi_div_vol_ok": True}

    def test_long_rsi15_above_50_ok(self):
        ok, _ = M4Entry.evaluate(
            "long", {**self._LONG, "tf15_rsi": 55.0}, _params(), ablation=3)
        assert ok is True

    def test_long_rsi15_below_50_blocked(self):
        ok, reason = M4Entry.evaluate(
            "long", {**self._LONG, "tf15_rsi": 45.0}, _params(), ablation=3)
        assert ok is False
        assert "G2" in reason

    def test_short_rsi15_below_50_ok(self):
        ok, _ = M4Entry.evaluate(
            "short", {**self._SHORT, "tf15_rsi": 45.0}, _params(), ablation=3)
        assert ok is True

    def test_short_rsi15_above_50_blocked(self):
        ok, reason = M4Entry.evaluate(
            "short", {**self._SHORT, "tf15_rsi": 55.0}, _params(), ablation=3)
        assert ok is False
        assert "G2" in reason

    def test_no_rsi15_key_blocked(self):
        ok, reason = M4Entry.evaluate(
            "long", self._LONG, _params(), ablation=3)
        assert ok is False
        assert "G2" in reason
        assert "데이터 없음" in reason

    def test_ablation2_skips_g2(self):
        # ablation=2: tf15_rsi 키 없어도 G2 미검사 → 통과
        ok, _ = M4Entry.evaluate(
            "long", {"rsi_div_bull": True, "rsi_div_vol_ok": True},
            _params(), ablation=2)
        assert ok is True


# ── TestG0Bias ─────────────────────────────────────────────────────────────

class TestG0Bias:
    """G0 방향 편향 — Sort by 모드별 제한 검증 (ablation=1)."""

    def test_both_mode_long_ok(self):
        ok, _ = M4Entry.evaluate(
            "long", {"rsi_div_bull": True}, _params("24h Ticker"), ablation=1)
        assert ok is True

    def test_both_mode_short_ok(self):
        ok, _ = M4Entry.evaluate(
            "short", {"rsi_div_bear": True}, _params("24h Ticker"), ablation=1)
        assert ok is True

    def test_long_only_mode_blocks_short(self):
        # Sharp rise: direction_bias="long_only"
        ok, reason = M4Entry.evaluate(
            "short", {"rsi_div_bear": True}, _params("Sharp rise"), ablation=1)
        assert ok is False
        assert "롱 전용" in reason

    def test_long_only_mode_allows_long(self):
        ok, _ = M4Entry.evaluate(
            "long", {"rsi_div_bull": True}, _params("Sharp rise"), ablation=1)
        assert ok is True


# ── TestDivergenceDetector ─────────────────────────────────────────────────

class TestDivergenceDetector:
    """DivergenceDetector.detect() 순수 함수 단독 검증.

    SWING_WINDOW=3: index i가 스윙 저점/고점 ↔ 양쪽 3봉 대비 극값.
    검증 패턴은 길이 20 리스트에서 i=5, i=14에 스윙 포인트를 배치.
    """

    @staticmethod
    def _bars(lows: list, highs: list) -> list:
        return [
            OHLCVBar(
                open_time=i, open=(l + h) / 2.0, high=h, low=l,
                close=(l + h) / 2.0, volume=100.0, quote_volume=100.0,
                close_time=i,
            )
            for i, (l, h) in enumerate(zip(lows, highs))
        ]

    def test_bull_detected(self):
        # 가격 저저점: i=5 저점=88, i=14 저점=81 (81 < 88 ✓)
        # K 고저점:    i=5 저점=35, i=14 저점=40 (40 > 35 ✓)
        lows  = [100, 95, 92, 91, 90, 88, 90, 92, 94,
                  96, 98, 99, 98, 96, 81, 83, 85, 87, 89, 91]
        highs = [l + 5.0 for l in lows]
        k_ser = [50.0, 45, 42, 41, 40, 35, 37, 39, 41,
                 43, 45, 46, 45, 44, 40, 42, 44, 46, 48, 50]
        bars = self._bars(lows, highs)
        assert DivergenceDetector.detect(bars, k_ser) == "bull"

    def test_bear_detected(self):
        # 가격 고고점: i=5 고점=112, i=14 고점=120 (120 > 112 ✓)
        # K 저고점:    i=5 고점=65,  i=14 고점=62  (62 < 65  ✓)
        highs = [100, 105, 108, 109, 110, 112, 110, 108, 106,
                 104, 102, 101, 102, 104, 120, 118, 116, 114, 112, 110]
        lows  = [h - 5.0 for h in highs]
        k_ser = [50.0, 55, 58, 59, 60, 65, 63, 61, 59,
                 57, 55, 54, 55, 57, 62, 60, 58, 56, 54, 52]
        bars = self._bars(lows, highs)
        assert DivergenceDetector.detect(bars, k_ser) == "bear"

    def test_no_divergence_flat(self):
        # 전구간 동일 값 → 스윙 포인트 없음 → None
        lows  = [100.0] * 20
        highs = [105.0] * 20
        k_ser = [50.0]  * 20
        bars = self._bars(lows, highs)
        assert DivergenceDetector.detect(bars, k_ser) is None

    def test_insufficient_k_data(self):
        # len(k_series) < SWING_WINDOW*2+1=7 → None
        lows  = [100.0] * 6
        highs = [105.0] * 6
        k_ser = [50.0]  * 6
        bars = self._bars(lows, highs)
        assert DivergenceDetector.detect(bars, k_ser) is None

    def test_bars_shorter_than_k_series(self):
        # len(bars) < len(k_series) → None
        lows  = [100.0] * 5
        highs = [105.0] * 5
        k_ser = [50.0]  * 10
        bars = self._bars(lows, highs)
        assert DivergenceDetector.detect(bars, k_ser) is None
