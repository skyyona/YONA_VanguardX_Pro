"""bottom/short_engine/short_order.py  숏 주문 실행"""
from __future__ import annotations
from bottom_engine.models import Order, OrderResult, OrderSide, OrderType, StrategyParams
from bottom_engine.api.binance_client import BottomBinanceClient

class ShortOrder:
    @staticmethod
    def execute(client: BottomBinanceClient, symbol: str,
                quantity: float, params: StrategyParams,
                mark: float = 0.0) -> OrderResult:
        if mark > 0:
            limit_order = Order(symbol=symbol, side=OrderSide.SELL,
                                order_type=OrderType.LIMIT, quantity=quantity,
                                price=mark, leverage=params.leverage,
                                stop_loss_pct=params.stop_loss,
                                trail_stop_pct=params.trail_stop)
            result = client.place_order(limit_order, mark)
            if result.success:
                return result
        market_order = Order(symbol=symbol, side=OrderSide.SELL,
                             order_type=OrderType.MARKET, quantity=quantity,
                             leverage=params.leverage,
                             stop_loss_pct=params.stop_loss,
                             trail_stop_pct=params.trail_stop)
        return client.place_order(market_order, mark)
