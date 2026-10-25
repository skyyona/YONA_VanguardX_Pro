"""
tests/bottom/test_binance_client.py
BottomBinanceClient MMR 캐시 관련 3건 + reduceOnly 4건 + Algo 주문 전환 9건 테스트.
mock/patch/MagicMock 사용 없음. 캐시 주입 방식으로 검증.
"""
import re
import time

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


class TestAlgoOrders:
    """SL·Trailing 조건부 주문 → Algo 주문(/fapi/v1/algoOrder) 전환 검증.
    Binance 2025-12-09 시행: 조건부 주문을 /fapi/v1/order로 보내면 -4120 거절."""

    _CLIENT_ALGO_ID = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")

    def _make_client(self):
        client = BottomBinanceClient()
        client._has_keys = True
        client._rate_limited_until = 0.0
        client._precision_cache["BTCUSDT"] = 3
        return client

    def _capture_post(self, captured: list, response: dict | None):
        def _capture(path, params):
            captured.append((path, dict(params)))
            return response
        return _capture

    def _capture_delete(self, captured: list, ok: bool):
        def _capture(path, params, label, ok_codes=()):
            captured.append((path, dict(params), ok_codes))
            return ok
        return _capture

    def test_stop_market_uses_algo_endpoint(self):
        """STOP_MARKET SL은 /fapi/v1/algoOrder로 algoType·triggerPrice·clientAlgoId를 보내고 algoId를 반환."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_post(captured, {"algoId": 2146760})
        oid = client.place_stop_market("BTCUSDT", "SELL", 49000.0)
        assert oid == "2146760"
        path, p = captured[0]
        assert path == "/fapi/v1/algoOrder"
        assert p["algoType"] == "CONDITIONAL"
        assert p["type"] == "STOP_MARKET"
        assert p["side"] == "SELL"
        assert p["triggerPrice"] == "49000.00000000"
        assert p["closePosition"] == "true"
        assert p["workingType"] == "MARK_PRICE"
        assert p["clientAlgoId"].startswith("sl_")
        assert self._CLIENT_ALGO_ID.match(p["clientAlgoId"])
        for legacy in ("stopPrice", "newClientOrderId"):
            assert legacy not in p
        # closePosition=true는 quantity·reduceOnly와 병용 불가 (공식 문서)
        assert "quantity" not in p
        assert "reduceOnly" not in p

    def test_trailing_stop_uses_algo_endpoint(self):
        """TRAILING_STOP_MARKET은 /fapi/v1/algoOrder로 quantity·reduceOnly를 보내고 closePosition은 보내지 않는다."""
        client = self._make_client()
        captured = []
        client._signed_post = self._capture_post(captured, {"algoId": 77})
        oid = client.place_trailing_stop("BTCUSDT", "BUY", 0.5, 0.0123)
        assert oid == "77"
        path, p = captured[0]
        assert path == "/fapi/v1/algoOrder"
        assert p["algoType"] == "CONDITIONAL"
        assert p["type"] == "TRAILING_STOP_MARKET"
        assert p["side"] == "BUY"
        assert p["callbackRate"] == "0.5"
        assert p["quantity"] == "0.012"
        assert p["reduceOnly"] == "true"
        assert p["workingType"] == "MARK_PRICE"
        assert p["clientAlgoId"].startswith("tr_")
        assert self._CLIENT_ALGO_ID.match(p["clientAlgoId"])
        assert "closePosition" not in p
        assert "newClientOrderId" not in p

    def test_algo_order_failure_returns_empty(self):
        """API 실패(None 응답) 시 SL·Trailing 모두 빈 문자열 반환."""
        client = self._make_client()
        client._signed_post = self._capture_post([], None)
        assert client.place_stop_market("BTCUSDT", "SELL", 49000.0) == ""
        assert client.place_trailing_stop("BTCUSDT", "SELL", 0.5, 0.01) == ""

    def test_cancel_order_uses_algo_endpoint(self):
        """SL·Trailing 취소는 DELETE /fapi/v1/algoOrder + algoId (symbol 미전송)."""
        client = self._make_client()
        captured = []
        client._signed_delete = self._capture_delete(captured, True)
        assert client.cancel_order("BTCUSDT", "2146760") is True
        path, p, _ = captured[0]
        assert path == "/fapi/v1/algoOrder"
        assert p["algoId"] == "2146760"
        assert "symbol" not in p
        assert "orderId" not in p

    def test_cancel_order_already_finished_is_success(self):
        """취소 실패 후 상태 조회에서 NEW가 아니면(이미 발동·종료) True."""
        client = self._make_client()
        client._signed_delete = self._capture_delete([], False)
        queried = []
        def _get(path, params=None):
            queried.append((path, dict(params or {})))
            return {"algoId": 2146760, "algoStatus": "FINISHED"}
        client._signed_get = _get
        assert client.cancel_order("BTCUSDT", "2146760") is True
        assert queried[0] == ("/fapi/v1/algoOrder", {"algoId": "2146760"})

    def test_cancel_order_still_new_is_failure(self):
        """취소 실패 후 상태가 NEW면 False, 취소 오류 문구 유지."""
        client = self._make_client()
        def _delete(path, params, label, ok_codes=()):
            client._last_api_error = "cancel_order [-1000] test"
            return False
        client._signed_delete = _delete
        def _get(path, params=None):
            client._last_api_error = ""
            return {"algoId": 2146760, "algoStatus": "NEW"}
        client._signed_get = _get
        assert client.cancel_order("BTCUSDT", "2146760") is False
        assert client._last_api_error == "cancel_order [-1000] test"

    def test_cancel_order_rate_limited_skips_status_query(self):
        """레이트리밋 중에는 상태 조회 없이 False."""
        client = self._make_client()
        client._signed_delete = self._capture_delete([], False)
        client._rate_limited_until = time.time() + 60
        queried = []
        client._signed_get = lambda path, params=None: queried.append(path)
        assert client.cancel_order("BTCUSDT", "2146760") is False
        assert queried == []

    def test_unfilled_limit_entry_cancels_via_regular_endpoint(self):
        """진입 LIMIT(GTX) 미체결 취소는 일반 주문 경로 DELETE /fapi/v1/order(-2011 성공 처리) 유지."""
        client = self._make_client()
        client._signed_post = lambda path, params: {
            "avgPrice": "0", "price": "50000", "executedQty": "0", "orderId": "999"}
        captured = []
        client._signed_delete = self._capture_delete(captured, True)
        result = client.place_order(Order(symbol="BTCUSDT", side=OrderSide.BUY,
                                          order_type=OrderType.LIMIT, quantity=0.001, price=50000.0))
        assert result.success is False
        path, p, ok_codes = captured[0]
        assert path == "/fapi/v1/order"
        assert p["symbol"] == "BTCUSDT"
        assert p["orderId"] == "999"
        assert ok_codes == (-2011,)

    def test_get_open_orders_uses_open_algo_orders(self):
        """SL 복구용 미체결 조회는 GET /fapi/v1/openAlgoOrders(symbol 지정, 가중치 1)."""
        client = self._make_client()
        queried = []
        def _get(path, params=None):
            queried.append((path, dict(params or {})))
            return [{"algoId": 1, "orderType": "STOP_MARKET", "side": "SELL"}]
        client._signed_get = _get
        result = client.get_open_orders("BTCUSDT")
        assert queried[0] == ("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"})
        assert result[0]["orderType"] == "STOP_MARKET"