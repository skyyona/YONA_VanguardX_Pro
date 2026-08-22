"""
tests/bottom/test_fourtf_consensus.py
FourTFConsensus 단위 테스트.
"""
from bottom_engine.engine_core.fourtf_consensus import FourTFConsensus, MIN_SPREAD


def _build(tf1_k=50.0, tf1_d=50.0,
           tf3_k=50.0, tf3_d=50.0,
           tf5_k=50.0, tf5_d=50.0,
           tf15_k=50.0, tf15_d=50.0) -> dict:
    return {
        "tf1":  {"k": tf1_k,  "d": tf1_d},
        "tf3":  {"k": tf3_k,  "d": tf3_d},
        "tf5":  {"k": tf5_k,  "d": tf5_d},
        "tf15": {"k": tf15_k, "d": tf15_d},
    }


def _all_long(spread: float = 5.0) -> dict:
    k, d = 60.0, 60.0 - spread
    return _build(k, d, k, d, k, d, k, d)


def _all_short(spread: float = 5.0) -> dict:
    k, d = 40.0, 40.0 + spread
    return _build(k, d, k, d, k, d, k, d)


class TestFourTFConsensusLong:
    def test_all_long_consensus(self):
        sig = FourTFConsensus.evaluate(_all_long())
        assert sig.long_consensus is True
        assert sig.short_consensus is False
        assert sig.aligned_long == 4

    def test_spread_exactly_min_triggers_long(self):
        """spread=MIN_SPREAD(2.0) → 경계값, 롱 합의 성립."""
        sig = FourTFConsensus.evaluate(_all_long(spread=MIN_SPREAD))
        assert sig.long_consensus is True

    def test_spread_below_min_no_long(self):
        """spread=1.9 < MIN_SPREAD → ↔ 방향 → 롱 합의 실패."""
        sig = FourTFConsensus.evaluate(_all_long(spread=1.9))
        assert sig.long_consensus is False
        assert sig.aligned_long == 0


class TestFourTFConsensusShort:
    def test_all_short_consensus(self):
        sig = FourTFConsensus.evaluate(_all_short())
        assert sig.short_consensus is True
        assert sig.long_consensus is False
        assert sig.aligned_short == 4

    def test_spread_exactly_min_triggers_short(self):
        sig = FourTFConsensus.evaluate(_all_short(spread=MIN_SPREAD))
        assert sig.short_consensus is True

    def test_spread_below_min_no_short(self):
        sig = FourTFConsensus.evaluate(_all_short(spread=1.9))
        assert sig.short_consensus is False
        assert sig.aligned_short == 0


class TestFourTFConsensusEdgeCases:
    def test_empty_dict_no_consensus(self):
        """빈 dict → 모든 TF k=50, d=50 기본값 → spread=0 → ↔ → 합의 없음."""
        sig = FourTFConsensus.evaluate({})
        assert sig.long_consensus is False
        assert sig.short_consensus is False
        assert sig.aligned_long == 0
        assert sig.aligned_short == 0

    def test_partial_tf_counts_correctly(self):
        """3TF 롱 + 1TF 중립 → long_consensus=False, aligned_long=3."""
        ind = {
            "tf1":  {"k": 65.0, "d": 60.0},   # spread=5 → ▲
            "tf3":  {"k": 65.0, "d": 60.0},   # ▲
            "tf5":  {"k": 65.0, "d": 60.0},   # ▲
            "tf15": {"k": 50.0, "d": 50.0},   # spread=0 → ↔
        }
        sig = FourTFConsensus.evaluate(ind)
        assert sig.long_consensus is False
        assert sig.aligned_long == 3

    def test_mixed_long_short_no_consensus(self):
        """롱 2TF + 숏 2TF → 양쪽 모두 합의 없음."""
        ind = {
            "tf1":  {"k": 70.0, "d": 60.0},   # ▲
            "tf3":  {"k": 70.0, "d": 60.0},   # ▲
            "tf5":  {"k": 30.0, "d": 40.0},   # ▼
            "tf15": {"k": 30.0, "d": 40.0},   # ▼
        }
        sig = FourTFConsensus.evaluate(ind)
        assert sig.long_consensus is False
        assert sig.short_consensus is False
        assert sig.aligned_long == 2
        assert sig.aligned_short == 2

    def test_details_contain_all_four_tf(self):
        """details에 1m·3m·5m·15m 키가 모두 포함된다."""
        sig = FourTFConsensus.evaluate(_all_long())
        assert set(sig.details.keys()) == {"1m", "3m", "5m", "15m"}

    def test_details_include_spread(self):
        """details 각 TF에 spread 필드가 있다."""
        sig = FourTFConsensus.evaluate(_all_long(spread=3.5))
        for tf_detail in sig.details.values():
            assert "spread" in tf_detail
            assert abs(tf_detail["spread"] - 3.5) < 1e-9

    def test_missing_tf_key_uses_defaults(self):
        """일부 TF 키 누락 → k=50, d=50 기본값 → 해당 TF는 ↔."""
        sig = FourTFConsensus.evaluate({"tf1": {"k": 65.0, "d": 60.0}})
        assert sig.long_consensus is False
        assert sig.aligned_long == 1
