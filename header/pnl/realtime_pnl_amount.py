"""Real-Time P&L Amount — 손익금액 (USDT) 계산"""


class RealtimePnlAmount:
    @staticmethod
    def calculate(initial_usdt: float, total_usdt: float) -> float:
        return round(total_usdt - initial_usdt, 4)
