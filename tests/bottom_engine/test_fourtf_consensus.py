"""
tests/bottom_engine/test_fourtf_consensus.py
FourTFConsensus 합의 판정 단위 테스트
"""
import pytest

from bottom_engine.engine_core.fourtf_consensus import FourTFConsensus, MIN_SPREAD


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _build(k: float, d: float) -> dict:
    return {"k": k, "d": d}


def _all_long(spread: float = MIN_SPREAD) -> dict:
    half = spread / 2.0
    tf = _build(50.0 + half, 50.0 - half)
    return {"tf1": tf, "tf3": tf, "tf5": tf, "tf15": tf}


def _all_short(spread: float = MIN_SPREAD) -> dict:
    half = spread / 2.0
    tf = _build(50.0 - half, 50.0 + half)
    return {"tf1": tf, "tf3": tf, "tf5": tf, "tf15": tf}


# ── 롱 합의 ─────────────────────────────────────────────────────────────────

class TestFourTFConsensusLong:
    def test_all_long_consensus(self):
        sig = FourTFConsensus.evaluate(_all_long(spread=5.0))
        assert sig.long_consensus is True
        assert sig.short_consensus is False
        assert sig.aligned_long == 4
        assert sig.aligned_short == 0

    def test_spread_exactly_min_triggers_long(self):
        sig = FourTFConsensus.evaluate(_all_long(spread=MIN_SPREAD))
        assert sig.long_consensus is True
        assert sig.aligned_long == 4

    def test_spread_below_min_no_long(self):
        sig = FourTFConsensus.evaluate(_all_long(spread=MIN_SPREAD - 0.1))
        assert sig.long_consensus is False
        assert sig.aligned_long == 0


# ── 숏 합의 ─────────────────────────────────────────────────────────────────

class TestFourTFConsensusShort:
    def test_all_short_consensus(self):
        sig = FourTFConsensus.evaluate(_all_short(spread=5.0))
        assert sig.short_consensus is True
        assert sig.long_consensus is False
        assert sig.aligned_short == 4
        assert sig.aligned_long == 0

    def test_spread_exactly_min_triggers_short(self):
        sig = FourTFConsensus.evaluate(_all_short(spread=MIN_SPREAD))
        assert sig.short_consensus is True
        assert sig.aligned_short == 4

    def test_spread_below_min_no_short(self):
        sig = FourTFConsensus.evaluate(_all_short(spread=MIN_SPREAD - 0.1))
        assert sig.short_consensus is False
        assert sig.aligned_short == 0


# ── 엣지 케이스 ──────────────────────────────────────────────────────────────

class TestFourTFConsensusEdgeCases:
    def test_empty_dict_no_consensus(self):
        sig = FourTFConsensus.evaluate({})
        assert sig.long_consensus is False
        assert sig.short_consensus is False
        assert sig.aligned_long == 0
        assert sig.aligned_short == 0

    def test_partial_tf_counts_correctly(self):
        half = MIN_SPREAD / 2.0
        long_tf  = _build(50.0 + half, 50.0 - half)
        neut_tf  = _build(50.0, 50.0)
        ind_data = {"tf1": long_tf, "tf3": long_tf, "tf5": long_tf, "tf15": neut_tf}
        sig = FourTFConsensus.evaluate(ind_data)
        assert sig.long_consensus is False
        assert sig.aligned_long == 3

    def test_mixed_long_short_no_consensus(self):
        half = MIN_SPREAD / 2.0
        long_tf  = _build(50.0 + half, 50.0 - half)
        short_tf = _build(50.0 - half, 50.0 + half)
        ind_data = {"tf1": long_tf, "tf3": long_tf, "tf5": short_tf, "tf15": short_tf}
        sig = FourTFConsensus.evaluate(ind_data)
        assert sig.long_consensus is False
        assert sig.short_consensus is False
        assert sig.aligned_long == 2
        assert sig.aligned_short == 2

    def test_details_contain_all_four_tf(self):
        sig = FourTFConsensus.evaluate(_all_long(spread=5.0))
        assert set(sig.details.keys()) == {"1m", "3m", "5m", "15m"}

    def test_details_include_spread(self):
        sig = FourTFConsensus.evaluate(_all_long(spread=5.0))
        for tf, detail in sig.details.items():
            assert "spread" in detail, f"{tf} details missing 'spread'"

    def test_missing_tf_key_uses_defaults(self):
        half = MIN_SPREAD / 2.0
        long_tf  = _build(50.0 + half, 50.0 - half)
        ind_data = {"tf1": long_tf, "tf3": long_tf, "tf5": long_tf}
        sig = FourTFConsensus.evaluate(ind_data)
        assert sig.long_consensus is False
        assert sig.aligned_long == 3
        assert "15m" in sig.details
        assert sig.details["15m"]["k"] == 50.0
        assert sig.details["15m"]["d"] == 50.0
