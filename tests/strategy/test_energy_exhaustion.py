"""
tests/strategy/test_energy_exhaustion.py
EnergyExhaustion + M4Exit(ENERGY) 단위 테스트.

mock/patch/MagicMock 사용 없음. 순수 함수 입력→출력 검증.
"""
import pytest
from bottom_engine.strategy.energy_exhaustion import EnergyExhaustion
from bottom_engine.strategy.m4_exit import M4Exit


# ── 더미 봉 객체 (속성만 있는 단순 네임스페이스) ─────────────────────────────

class _Bar:
    def __init__(self, o, h, l, c):
        self.open = o; self.high = h; self.low = l; self.close = c


def _make_bars(bpr_values: list[float], base: float = 100.0) -> list[_Bar]:
    """BPR 목표값에 맞는 봉 생성 (high=base+1, low=base-1, close=low+rng*bpr)."""
    bars = []
    lo, hi = base - 1.0, base + 1.0
    rng = hi - lo
    for v in bpr_values:
        close = lo + rng * v
        bars.append(_Bar(o=base, h=hi, l=lo, c=close))
    return bars


# ── EnergyExhaustion.check_exhaustion ────────────────────────────────────

class TestCheckExhaustion:
    def test_bear_exhausted_true(self):
        # prev 3봉 BPR ≈ 0.40 (소멸 임계), cur 3봉 BPR ≈ 0.52 (반전 확인)
        bars = _make_bars([0.40, 0.40, 0.40, 0.52, 0.52, 0.52])
        bear, bull = EnergyExhaustion.check_exhaustion(bars)
        assert bear is True
        assert bull is False

    def test_bull_exhausted_true(self):
        # prev 3봉 BPR ≈ 0.60, cur 3봉 BPR ≈ 0.48
        bars = _make_bars([0.60, 0.60, 0.60, 0.48, 0.48, 0.48])
        bear, bull = EnergyExhaustion.check_exhaustion(bars)
        assert bear is False
        assert bull is True

    def test_neither_exhausted(self):
        bars = _make_bars([0.50, 0.50, 0.50, 0.50, 0.50, 0.50])
        bear, bull = EnergyExhaustion.check_exhaustion(bars)
        assert bear is False
        assert bull is False

    def test_insufficient_bars(self):
        bars = _make_bars([0.40, 0.40, 0.52])  # 3봉 (< 6)
        bear, bull = EnergyExhaustion.check_exhaustion(bars)
        assert bear is False
        assert bull is False

    def test_bear_prev_boundary(self):
        # prev BPR = 0.41 (임계 초과) → False
        bars = _make_bars([0.41, 0.41, 0.41, 0.52, 0.52, 0.52])
        bear, _ = EnergyExhaustion.check_exhaustion(bars)
        assert bear is False

    def test_bear_cur_boundary(self):
        # cur BPR = 0.51 (임계 미달) → False
        bars = _make_bars([0.40, 0.40, 0.40, 0.51, 0.51, 0.51])
        bear, _ = EnergyExhaustion.check_exhaustion(bars)
        assert bear is False


# ── EnergyExhaustion.check_trigger ───────────────────────────────────────

class TestCheckTrigger:
    def test_long_trigger(self):
        assert EnergyExhaustion.check_trigger(20.0, 20.1, "long") is True

    def test_long_trigger_exact_boundary(self):
        # prev_K = 20.0 (≤ 20) → True
        assert EnergyExhaustion.check_trigger(20.0, 21.0, "long") is True

    def test_long_trigger_false_prev_too_high(self):
        # prev_K = 20.1 (> 20) → False
        assert EnergyExhaustion.check_trigger(20.1, 25.0, "long") is False

    def test_long_trigger_false_cur_not_above(self):
        # cur_K = 20.0 (≤ 20) → False
        assert EnergyExhaustion.check_trigger(15.0, 20.0, "long") is False

    def test_short_trigger(self):
        assert EnergyExhaustion.check_trigger(80.0, 79.9, "short") is True

    def test_short_trigger_exact_boundary(self):
        # prev_K = 80.0 (≥ 80) → True
        assert EnergyExhaustion.check_trigger(80.0, 79.0, "short") is True

    def test_short_trigger_false_prev_too_low(self):
        # prev_K = 79.9 (< 80) → False
        assert EnergyExhaustion.check_trigger(79.9, 75.0, "short") is False

    def test_short_trigger_false_cur_not_below(self):
        # cur_K = 80.0 (≥ 80) → False
        assert EnergyExhaustion.check_trigger(85.0, 80.0, "short") is False


# ── M4Exit.evaluate exit_variant="ENERGY" ────────────────────────────────

ENTRY = 100.0
SL_PCT = 3.7


class TestEnergyExitLong:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="LONG", phase=1, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=1.1,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
            exit_variant="ENERGY",
        )

    def test_sl_hit(self):
        sl_price = ENTRY * (1.0 - SL_PCT / 100.0)
        dec = self._eval(hi=ENTRY, lo=sl_price - 0.01, close=sl_price)
        assert dec.reason == "SL"
        assert dec.exit_price == pytest.approx(sl_price)
        assert dec.qty_ratio == 1.0

    def test_kd_exit_long(self):
        dec = self._eval(hi=ENTRY + 1, lo=ENTRY - 0.5, close=ENTRY,
                         k_prev=80.0, k_cur=79.9)
        assert dec.reason == "KD-EXIT"
        assert dec.exit_price == ENTRY
        assert dec.qty_ratio == 1.0

    def test_no_exit(self):
        dec = self._eval(hi=ENTRY + 1, lo=ENTRY - 0.5, close=ENTRY,
                         k_prev=50.0, k_cur=55.0)
        assert dec.reason == ""


class TestEnergyExitShort:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="SHORT", phase=1, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=1.1,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
            exit_variant="ENERGY",
        )

    def test_sl_hit(self):
        sl_price = ENTRY * (1.0 + SL_PCT / 100.0)
        dec = self._eval(hi=sl_price + 0.01, lo=ENTRY, close=sl_price)
        assert dec.reason == "SL"
        assert dec.exit_price == pytest.approx(sl_price)
        assert dec.qty_ratio == 1.0

    def test_kd_exit_short(self):
        dec = self._eval(hi=ENTRY + 0.5, lo=ENTRY - 1, close=ENTRY,
                         k_prev=20.0, k_cur=20.1)
        assert dec.reason == "KD-EXIT"
        assert dec.exit_price == ENTRY
        assert dec.qty_ratio == 1.0

    def test_no_exit(self):
        dec = self._eval(hi=ENTRY + 0.5, lo=ENTRY - 0.5, close=ENTRY,
                         k_prev=50.0, k_cur=45.0)
        assert dec.reason == ""
