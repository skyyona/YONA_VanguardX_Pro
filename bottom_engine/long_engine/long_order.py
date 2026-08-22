"""bottom/long_engine/long_order.py  롱 주문 실행"""
from __future__ import annotations
from bottom_engine.models import Order, OrderResult, OrderSide, OrderType, StrategyParams
from bottom_engine.api.binance_client import BottomBinanceClient

class LongOrder:
    @staticmethod
    def execute(client: BottomBinanceClient, symbol: str,
                quantity: float, params: StrategyParams,
                mark: float = 0.0) -> OrderResult:
        order = Order(symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET,
                      quantity=quantity, leverage=params.leverage,
                      stop_loss_pct=params.stop_loss, trail_stop_pct=params.trail_stop)
        return client.place_order(order, mark)
