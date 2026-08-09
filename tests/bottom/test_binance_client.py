"""
tests/bottom/test_binance_client.py
BottomBinanceClient MMR 캐시 관련 3건 테스트.
mock/patch/MagicMock 사용 없음. 캐시 주입 방식으로 검증.
"""
from bottom.api.binance_client import BottomBinanceClient, _MMR_FALLBACK


class TestMmrCached:
    def test_cache_hit_returns_injected_value(self):
        """캐시에 값을 직접 주입했을 때 get_mmr_cached()가 그 값을 반환한다."""
        client = BottomBinanceClient()
        client._mmr_cache["BTCUSDT"] = 0.025
        assert client.get_mmr_cached("BTCUSDT") == 0.025

    def test_cache_miss_returns_fallback(self):
        """캐시에 없는 심볼은 get_mmr_cached()가 _MMR_FALLBACK을 반환한다."""
        client = BottomBinanceClient()
        assert client.get_mmr_cached("ETHUSDT") == _MMR_FALLBACK

    def test_get_mmr_populates_cache_on_no_keys(self):
        """API 키 없음(_has_keys=False) 상태에서 get_mmr()는 캐시 미사용, _MMR_FALLBACK 반환."""
        client = BottomBinanceClient()
        client._has_keys = False
        result = client.get_mmr("XRPUSDT")
        assert result == _MMR_FALLBACK
        assert "XRPUSDT" not in client._mmr_cache