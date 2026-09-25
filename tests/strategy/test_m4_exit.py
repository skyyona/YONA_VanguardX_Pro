"""
tests/strategy/test_m4_exit.py
M4Exit.evaluate() 단위 테스트 — BT·LIVE 공통 청산 판정 로직.

mock/patch/MagicMock 사용 없음. 순수 함수 입력→출력 검증.
"""
import pytest
from bottom_engine.strategy.m4_exit import M4Exit, ExitDecision

# ── 테스트 상수 ─────────────────────────────────────────────────────────
ENTRY = 100.0
SL_PCT = 3.7      # R = 3.7
TRAIL_PCT = 1.1
R = ENTRY * SL_PCT / 100.0   # = 3.7


# ── Long Phase1 ─────────────────────────────────────────────────────────

class TestLongPhase1:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="LONG", phase=1, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_sl_hit(self):
        sl_p1 = ENTRY * (1.0 - SL_PCT / 100.0)   # 96.3
        dec = self._eval(hi=ENTRY, lo=sl_p1 - 0.01, close=sl_p1)
        assert dec.reason == "SL"
        assert dec.exit_price == pytest.approx(sl_p1)
        assert dec.qty_ratio == 1.0
        assert dec.new_phase == 1

    def test_sl_exact_boundary(self):
        sl_p1 = ENTRY * (1.0 - SL_PCT / 100.0)
        dec = self._eval(hi=ENTRY, lo=sl_p1, close=sl_p1)
        assert dec.reason == "SL"

    def test_kd_exit(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 1.0, close=ENTRY,
                         k_prev=80.0, k_cur=79.9)
        assert dec.reason == "KD-EXIT"
        assert dec.exit_price == ENTRY
        assert dec.qty_ratio == 1.0

    def test_phase1_to_2_transition(self):
        # bar.high ≥ entry + R → Phase2
        dec = self._eval(hi=ENTRY + R, lo=ENTRY - 0.1, close=ENTRY)
        assert dec.reason == ""
        assert dec.new_phase == 2
        assert dec.new_sl == pytest.approx(ENTRY)

    def test_no_action(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 1.0, close=ENTRY)
        assert dec.reason == ""
        assert dec.new_phase == 1


# ── Long Phase2 ─────────────────────────────────────────────────────────

class TestLongPhase2:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="LONG", phase=2, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_bep_sl(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 0.01, close=ENTRY)
        assert dec.reason == "BEP-SL"
        assert dec.exit_price == pytest.approx(ENTRY)
        assert dec.qty_ratio == 1.0

    def test_kd_exit(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY + 0.5, close=ENTRY + 0.5,
                         k_prev=80.0, k_cur=79.9)
        assert dec.reason == "KD-EXIT"

    def test_partial(self):
        # bar.high ≥ entry + 1.5R → PARTIAL 50%
        dec = self._eval(hi=ENTRY + R * 1.5, lo=ENTRY + 0.5, close=ENTRY + 1.0)
        assert dec.reason == "PARTIAL"
        assert dec.exit_price == pytest.approx(ENTRY + R * 1.5)
        assert dec.qty_ratio == 0.5
        assert dec.new_phase == 3
        assert dec.new_trail_ref > 0.0
        assert dec.new_profit_trigger > 0.0

    def test_no_action(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY + 0.5, close=ENTRY + 0.8)
        assert dec.reason == ""
        assert dec.new_phase == 2
        assert dec.new_sl == pytest.approx(ENTRY)


# ── Long Phase3 ─────────────────────────────────────────────────────────

class TestLongPhase3:
    TRAIL_REF = ENTRY + R * 2.0   # 트레일링 기준가

    def _eval(self, hi, lo, close, profit_trigger=0.0, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="LONG", phase=3, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=self.TRAIL_REF, profit_trigger=profit_trigger,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_trail_hit(self):
        # profit_trigger=0 → trail 즉시 활성
        trail_sl = self.TRAIL_REF * (1.0 - TRAIL_PCT / 100.0)
        dec = self._eval(hi=self.TRAIL_REF, lo=trail_sl - 0.01, close=trail_sl)
        assert dec.reason == "TRAIL"
        assert dec.exit_price == pytest.approx(trail_sl)
        assert dec.qty_ratio == 0.5

    def test_bep_sl_when_no_trigger(self):
        # profit_trigger > close → BEP SL 유지
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 0.01, close=ENTRY,
                         profit_trigger=ENTRY + 5.0)
        assert dec.reason == "BEP-SL"
        assert dec.exit_price == pytest.approx(ENTRY)
        assert dec.qty_ratio == 0.5

    def test_kd_exit_trail_active(self):
        dec = self._eval(hi=self.TRAIL_REF, lo=self.TRAIL_REF - 0.1,
                         close=self.TRAIL_REF - 0.1, k_prev=80.0, k_cur=79.9)
        assert dec.reason == "KD-EXIT"
        assert dec.qty_ratio == 0.5

    def test_no_action_trail_active(self):
        close = self.TRAIL_REF - 0.1
        dec = self._eval(hi=self.TRAIL_REF, lo=close, close=close)
        assert dec.reason == ""
        assert dec.new_phase == 3
        assert dec.new_trail_ref > 0.0


# ── Short Phase1 ─────────────────────────────────────────────────────────

class TestShortPhase1:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="SHORT", phase=1, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_sl_hit(self):
        sl_p1 = ENTRY * (1.0 + SL_PCT / 100.0)   # 103.7
        dec = self._eval(hi=sl_p1 + 0.01, lo=ENTRY, close=sl_p1)
        assert dec.reason == "SL"
        assert dec.exit_price == pytest.approx(sl_p1)
        assert dec.qty_ratio == 1.0

    def test_kd_exit(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 1.0, close=ENTRY,
                         k_prev=20.0, k_cur=20.1)
        assert dec.reason == "KD-EXIT"

    def test_phase1_to_2_transition(self):
        # bar.low ≤ entry − R → Phase2
        dec = self._eval(hi=ENTRY - 0.1, lo=ENTRY - R, close=ENTRY)
        assert dec.reason == ""
        assert dec.new_phase == 2
        assert dec.new_sl == pytest.approx(ENTRY)

    def test_no_action(self):
        dec = self._eval(hi=ENTRY + 1.0, lo=ENTRY - 1.0, close=ENTRY)
        assert dec.reason == ""
        assert dec.new_phase == 1


# ── Short Phase2 ─────────────────────────────────────────────────────────

class TestShortPhase2:
    def _eval(self, hi, lo, close, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="SHORT", phase=2, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=0.0, profit_trigger=0.0,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_bep_sl(self):
        dec = self._eval(hi=ENTRY + 0.01, lo=ENTRY - 1.0, close=ENTRY)
        assert dec.reason == "BEP-SL"
        assert dec.exit_price == pytest.approx(ENTRY)

    def test_kd_exit(self):
        dec = self._eval(hi=ENTRY - 0.5, lo=ENTRY - 1.0, close=ENTRY - 0.5,
                         k_prev=20.0, k_cur=20.1)
        assert dec.reason == "KD-EXIT"

    def test_partial(self):
        # bar.low ≤ entry − 1.5R → PARTIAL 50%
        dec = self._eval(hi=ENTRY - 0.5, lo=ENTRY - R * 1.5, close=ENTRY - 1.0)
        assert dec.reason == "PARTIAL"
        assert dec.exit_price == pytest.approx(ENTRY - R * 1.5)
        assert dec.qty_ratio == 0.5
        assert dec.new_phase == 3
        assert dec.new_trail_ref > 0.0
        assert dec.new_profit_trigger > 0.0

    def test_no_action(self):
        dec = self._eval(hi=ENTRY - 0.5, lo=ENTRY - 1.0, close=ENTRY - 0.8)
        assert dec.reason == ""
        assert dec.new_phase == 2


# ── Short Phase3 ─────────────────────────────────────────────────────────

class TestShortPhase3:
    TRAIL_REF = ENTRY - R * 2.0   # trailing_low 기준가

    def _eval(self, hi, lo, close, profit_trigger=0.0, k_prev=0.0, k_cur=0.0):
        return M4Exit.evaluate(
            side="SHORT", phase=3, entry_price=ENTRY,
            sl_pct=SL_PCT, trail_pct=TRAIL_PCT,
            trail_ref=self.TRAIL_REF, profit_trigger=profit_trigger,
            hi=hi, lo=lo, close=close,
            k_prev=k_prev, k_cur=k_cur,
        )

    def test_trail_hit(self):
        # profit_trigger=0 → trail 즉시 활성
        trail_sl = self.TRAIL_REF * (1.0 + TRAIL_PCT / 100.0)
        dec = self._eval(hi=trail_sl + 0.01, lo=self.TRAIL_REF, close=trail_sl)
        assert dec.reason == "TRAIL"
        assert dec.exit_price == pytest.approx(trail_sl)
        assert dec.qty_ratio == 0.5

    def test_bep_sl_when_no_trigger(self):
        # profit_trigger < close → BEP SL 유지 (SHORT: close > profit_trigger = no trail)
        dec = self._eval(hi=ENTRY + 0.01, lo=ENTRY - 1.0, close=ENTRY,
                         profit_trigger=ENTRY - 5.0)
        assert dec.reason == "BEP-SL"
        assert dec.exit_price == pytest.approx(ENTRY)
        assert dec.qty_ratio == 0.5

    def test_kd_exit_trail_active(self):
        close = self.TRAIL_REF + 0.1
        dec = self._eval(hi=close, lo=self.TRAIL_REF, close=close,
                         k_prev=20.0, k_cur=20.1)
        assert dec.reason == "KD-EXIT"
        assert dec.qty_ratio == 0.5

    def test_no_action_trail_active(self):
        close = self.TRAIL_REF + 0.1
        dec = self._eval(hi=close, lo=self.TRAIL_REF, close=close)
        assert dec.reason == ""
        assert dec.new_phase == 3
        assert dec.new_trail_ref > 0.0
