"""
tests/bottom/test_sl_calculator.py
SLCalculator 단위 테스트.
"""
from bottom_engine.engine_core.sl_calculator import SLCalculator


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
        """lev=100 → liq_safe=max(0.001,(1/100-0.004))×100×0.8=0.48 → sl=0.5."""
        sl, _ = SLCalculator.compute(5.0, "D", 100)
        assert sl == 0.5

    def test_high_leverage_trail_floor_applies(self):
        """cap으로 trail이 0.2 아래로 내려가지 않음: sl=0.5, sl*0.6=0.3 → trail=0.3."""
        # sl=0.5, trail_raw=2.5, cap=sl*0.6=0.3, _TRAIL_MIN=0.2 → max(0.2,0.3)=0.3
        _, trail = SLCalculator.compute(5.0, "D", 100)
        assert trail == 0.3

    def test_liq_safe_80pct_of_theoretical(self):
        """청산 이론가의 80%가 상한: lev=5 → liq_safe=16.0."""
        sl, _ = SLCalculator.compute(1.0, "A", 5)
        # sl_raw=2.0, liq_safe=16.0 → sl=2.0 (cap 미적용)
        assert sl == 2.0


class TestSLCalculatorTrailCap:
    def test_trail_capped_at_sl_times_0_6(self):
        """trail_raw > sl×0.6 이면 trail이 sl×60%로 상한 적용."""
        # atr=10.0, grade=A, lev=10:
        # sl_raw=20→liq_safe=7.68(MMR반영)→sl=7.7 / trail_raw=5.0→min(5.0,4.608)=4.6
        sl, trail = SLCalculator.compute(10.0, "A", 10)
        assert sl == 7.7
        assert trail == 4.6
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
        """trail은 최소 0.2."""
        # atr=0.1, D → sl=0.3, trail_raw=0.05, cap=0.18, floor=0.2 → trail=0.2
        _, trail = SLCalculator.compute(0.1, "D", 10)
        assert trail == 0.2

    def test_output_rounded_to_1_decimal(self):
        """반환값은 소수점 1자리."""
        sl, trail = SLCalculator.compute(1.23, "B", 10)
        assert sl == round(sl, 1)
        assert trail == round(trail, 1)


# ── [C-2] SLCalculator.clamp() — T-1~T-3 ─────────────────────────────────────

class TestClampLiqSafePath:
    """T-1: stop_loss > liq_safe 시 clamp()와 compute() liq_safe 경로가 동일한 sl 반환."""

    def test_clamp_matches_compute_when_liq_safe_triggers(self):
        # lev=10, mmr=0.004 → liq_safe=7.68 → round → 7.7
        # compute: atr=10×grade_A(2.0)=20 > liq_safe → sl=7.7
        # clamp:   stop_loss=10.0 > liq_safe → sl=7.7
        sl_clamp, _ = SLCalculator.clamp(10.0, 1.0, 10, mmr=0.004)
        sl_compute, _ = SLCalculator.compute(10.0, "A", 10, mmr=0.004)
        assert sl_clamp == sl_compute

    def test_clamp_matches_compute_high_leverage(self):
        # lev=25, mmr=0.004 → liq_safe=2.88 → round → 2.9
        # compute: atr=5×grade_A(2.0)=10 > 2.9 → sl=2.9
        # clamp:   stop_loss=5.0 > 2.9 → sl=2.9
        sl_clamp, _ = SLCalculator.clamp(5.0, 1.0, 25, mmr=0.004)
        sl_compute, _ = SLCalculator.compute(5.0, "A", 25, mmr=0.004)
        assert sl_clamp == sl_compute


class TestClampRoundDecimal:
    """T-2: clamp() 반환값이 소수점 1자리임을 확인 (compute()와 동일한 round 적용)."""

    def test_sl_is_1_decimal(self):
        sl, _ = SLCalculator.clamp(3.68, 1.6, 20)
        assert sl == round(sl, 1)

    def test_trail_is_1_decimal(self):
        _, trail = SLCalculator.clamp(1.6, 1.0, 25)
        assert trail == round(trail, 1)

    def test_sharp_decline_trail_rounds_correctly(self):
        # stop_loss=1.6, lev=25 → sl_used=1.6, trail_raw=1.0×0.6=0.96 → round → 1.0
        _, trail = SLCalculator.clamp(1.6, 1.0, 25)
        assert trail == 1.0


class TestClampUserValuePassthrough:
    """T-3: stop_loss < liq_safe 시 사용자 설정값이 클램프 없이 반환."""

    def test_user_sl_preserved_when_safe(self):
        # lev=10, liq_safe=7.68 → stop_loss=2.5 통과
        sl, _ = SLCalculator.clamp(2.5, 1.5, 10)
        assert sl == 2.5

    def test_user_trail_preserved_when_safe(self):
        # lev=10, sl_used=2.5, sl×0.6=1.5 → trail=1.5 통과
        _, trail = SLCalculator.clamp(2.5, 1.5, 10)
        assert trail == 1.5

    def test_sl_min_floor_still_applies(self):
        # stop_loss=0.1 < _SL_MIN=0.3 → floor
        sl, _ = SLCalculator.clamp(0.1, 1.0, 10)
        assert sl == 0.3


# ── [C-2] T-4: clamp() sl이 liq_safe 상한을 절대 초과하지 않음 ──────────────

class TestClampNeverExceedsLiqSafe:
    """T-4: stop_loss가 liq_safe보다 크더라도 반환 sl은 liq_safe 이내."""

    def test_sl_capped_at_liq_safe_lev10(self):
        # lev=10, mmr=0.004 → liq_safe=(0.1-0.004)*100*0.8=7.68
        sl, _ = SLCalculator.clamp(10.0, 5.0, 10, mmr=0.004)
        liq_safe = max(0.001, (1.0 / 10 - 0.004)) * 100.0 * 0.80
        assert sl <= round(liq_safe, 1) + 1e-9

    def test_sl_capped_at_liq_safe_lev25(self):
        # lev=25, mmr=0.004 → liq_safe=(0.04-0.004)*100*0.8=2.88 → round=2.9
        sl, _ = SLCalculator.clamp(5.0, 2.0, 25, mmr=0.004)
        liq_safe = max(0.001, (1.0 / 25 - 0.004)) * 100.0 * 0.80
        assert sl <= round(liq_safe, 1) + 1e-9

    def test_update_params_sl_price_within_liq_safe(self):
        """clamp된 sl_up을 entry_price에 적용했을 때 SL가격의 이탈률이 liq_safe 이내."""
        sl_up, _ = SLCalculator.clamp(10.0, 5.0, 10, mmr=0.004)
        entry = 100.0
        sl_price = round(entry * (1 - sl_up / 100), 8)
        implied_pct = (entry - sl_price) / entry * 100
        liq_safe = max(0.001, (1.0 / 10 - 0.004)) * 100.0 * 0.80
        assert implied_pct <= round(liq_safe, 1) + 1e-9
