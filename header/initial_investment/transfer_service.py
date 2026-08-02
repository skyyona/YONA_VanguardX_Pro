"""
Spot ↔ Futures 자금 이체 실행 및 초기 투자금 기준값 관리
"""
from __future__ import annotations
import time
from header.api.binance_client import HeaderBinanceClient
from header.models import TransferDirection, WalletBalanceResult, WalletQueryStatus


class TransferService:
    def __init__(self, client: HeaderBinanceClient) -> None:
        self._client = client
        self._initial_investment_usdt: float = 0.0

    # ── 초기 투자금 기준값 ─────────────────────────────────────
    def set_initial_investment(self, amount_usdt: float) -> None:
        if amount_usdt < 0:
            raise ValueError("initial investment must not be negative")
        self._initial_investment_usdt = amount_usdt

    def get_initial_investment(self) -> float:
        return self._initial_investment_usdt

    # ── 이체 + 기준값 설정 ─────────────────────────────────────
    def apply_initial_investment(
        self,
        transfer_amount_usdt: float,
        direction: TransferDirection = TransferDirection.TO_FUTURES,
    ) -> WalletBalanceResult:
        if transfer_amount_usdt > 0:
            if direction == TransferDirection.TO_FUTURES:
                ok = self._client.transfer_spot_to_futures(transfer_amount_usdt)
            else:
                ok = self._client.transfer_futures_to_spot(transfer_amount_usdt)
            if not ok:
                return WalletBalanceResult(WalletQueryStatus.COMM_ERROR, 0.0)
            time.sleep(1.0)

        result = self._client.fetch_futures_total_balance_with_status()
        if result.status == WalletQueryStatus.OK:
            self.set_initial_investment(result.value_usdt)
        return result
