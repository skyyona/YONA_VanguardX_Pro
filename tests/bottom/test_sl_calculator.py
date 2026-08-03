"""
tests/bottom/test_sl_calculator.py
SLCalculator 단위 테스트.
"""
from bottom.engine_core.sl_calculator import SLCalculator


class TestSLCalculatorZeroAtr:
    def test_zero_atr_returns_zero_tuple(self):
        assert SLCalculator.compute(0.0, "A", 10) == (0.0, 0.0)

    def test_negative_atr_returns_zero_tuple(self):
        assert SLCalculator.compute(-0.5, "B", 10) == (0.0, 0.0)


class TestSLCalculatorGradeMultiplier:
    """각 등급별 배수(A=2.0, B=1.6, C=1.2, D=1.0) 적용 확인 — lev=10, atr=1.0."""

    def test_grade_a(self):
        # sl_raw=2.0, liq_safe=8.0 → sl=2.0 / trail_raw=0.5 → trail=0.5
        assert SLCalculator.compute(1.0, "A", 10) == (2.0, 0.5)

    def test_grade_b(self):
        # sl_raw=1.6, liq_safe=8.0 → sl=1.6 / trail=0.5
        assert SLCalculator.compute(1.0, "B", 10) == (1.6, 0.5)

    def test_grade_c(self):
        # sl_raw=1.2, liq_safe=8.0 → sl=1.2 / trail=0.5
        assert SLCalculator.compute(1.0, "C", 10) == (1.2, 0.5)

    def test_grade_d(self):
        # sl_raw=1.0, liq_safe=8.0 → sl=1.0 / trail=0.5
        assert SLCalculator.compute(1.0, "D", 10) == (1.0, 0.5)

    def test_unknown_grade_uses_1x(self):
        # 알 수 없는 등급 → mult=1.0 (dict.get 기본값)
        assert SLCalculator.compute(1.0, "X", 10) == SLCalculator.compute(1.0, "D", 10)


class TestSLCalculatorLeverageCap:
    def test_high_leverage_caps_sl(self):
        """lev=100 → liq_safe=(1/100)×100×0.8=0.8 → sl 상한 0.8."""
        sl, _ = SLCalculator.compute(5.0, "D", 100)
        assert sl == 0.8

    def test_high_leverage_trail_floor_applies(self):
        """cap으로 trail이 0.5 아래로 내려갈 때 floor 재보정 → trail=0.5."""
        # sl=0.8, sl*0.6=0.48 < _TRAIL_MIN(0.5) → floor 재보정 → 0.5
        _, trail = SLCalculator.compute(5.0, "D", 100)
        assert trail == 0.5

    def test_liq_safe_80pct_of_theoretical(self):
        """청산 이론가의 80%가 상한: lev=5 → liq_safe=16.0."""
        sl, _ = SLCalculator.compute(1.0, "A", 5)
        # sl_raw=2.0, liq_safe=16.0 → sl=2.0 (cap 미적용)
        assert sl == 2.0


class TestSLCalculatorTrailCap:
    def test_trail_capped_at_sl_times_0_6(self):
        """trail_raw > sl×0.6 이면 trail이 sl×60%로 상한 적용."""
        # atr=10.0, grade=A, lev=10:
        # sl_raw=20→liq_safe=8.0→sl=8.0 / trail_raw=5.0→min(5.0,4.8)=4.8
        sl, trail = SLCalculator.compute(10.0, "A", 10)
        assert sl == 8.0
        assert trail == 4.8
        assert trail <= sl * 0.6 + 1e-9

    def test_trail_not_capped_when_below_60pct(self):
        """trail_raw < sl×0.6 → cap 미적용."""
        # atr=3.0, grade=A, lev=10:
        # sl_raw=6.0, liq_safe=8.0→sl=6.0 / trail_raw=1.5→min(1.5,3.6)=1.5
        sl, trail = SLCalculator.compute(3.0, "A", 10)
        assert sl == 6.0
        assert trail == 1.5


class TestSLCalculatorFloors:
    def test_sl_min_floor(self):
        """sl은 최소 0.3."""
        # atr=0.1, grade=D → sl_raw=0.1 < 0.3 → floor
        sl, _ = SLCalculator.compute(0.1, "D", 10)
        assert sl == 0.3

    def test_trail_min_floor(self):
        """trail은 최소 0.5."""
        _, trail = SLCalculator.compute(0.1, "D", 10)
        assert trail == 0.5

    def test_output_rounded_to_1_decimal(self):
        """반환값은 소수점 1자리."""
        sl, trail = SLCalculator.compute(1.23, "B", 10)
        assert sl == round(sl, 1)
        assert trail == round(trail, 1)
