"""
tests/bottom/test_binance_client.py
BottomBinanceClient MMR 캐시 관련 3건 + reduceOnly 4건 테스트.
mock/patch/MagicMock 사용 없음. 캐시 주입 방식으로 검증.
"""
from bottom_engine.api.binance_client import BottomBinanceClient, _MMR_FALLBACK
from bottom_engine.models import Order, OrderSide, OrderType


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


class TestReduceOnly:
    """Order.reduce_only → _live_order params["reduceOnly"] 전달 검증."""

    def _make_client(self):
        client = BottomBinanceClient()
        client._precision_cache["BTCUSDT"] = 3
        return client

    def _capture_fn(self, captured: list):
        def _capture(path, params):
            captured.append(dict(params))
            return {
                "avgPrice": "50000.0",
                "price": "0",
                "executedQty": "0.001",
                "orderId": "12345",
            }
        return _capture

    def test_reduce_only_true_sends_flag(self):
        """reduce_only=True 주문은 params에 reduceOnly='true'가 포함된다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        order = Order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=0.001,
            reduce_only=True,
        )
        client.place_order(order)
        assert len(captured) == 1
        assert captured[0].get("reduceOnly") == "true"

    def test_reduce_only_false_omits_flag(self):
        """reduce_only=False(기본값) 주문은 params에 reduceOnly가 없다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        order = Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )
        client.place_order(order)
        assert len(captured) == 1
        assert "reduceOnly" not in captured[0]

    def test_close_position_sends_reduce_only(self):
        """close_position()은 항상 reduceOnly='true'를 포함한다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        client.close_position("BTCUSDT", "long", 0.001)
        assert len(captured) == 1
        assert captured[0].get("reduceOnly") == "true"
        assert captured[0].get("side") == "SELL"

    def test_place_order_default_no_reduce_only(self):
        """일반 place_order()는 reduce_only 미지정 시 reduceOnly를 보내지 않는다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        order = Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )
        client.place_order(order)
        assert len(captured) == 1
        assert "reduceOnly" not in captured[0]

    def test_close_short_sends_reduce_only(self):
        """숏 청산(close_position 'short')은 BUY + reduceOnly='true'."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        client.close_position("BTCUSDT", "short", 0.001)
        assert captured[0].get("side") == "BUY"
        assert captured[0].get("reduceOnly") == "true"

    def test_entry_limit_order_has_no_reduce_only(self):
        """LIMIT(GTX) 진입 주문에는 reduceOnly가 붙지 않는다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_fn(captured)
        client.place_order(Order(symbol="BTCUSDT", side=OrderSide.SELL,
                                 order_type=OrderType.LIMIT, quantity=0.001, price=50000.0))
        assert captured[0].get("timeInForce") == "GTX"
        assert "reduceOnly" not in captured[0]