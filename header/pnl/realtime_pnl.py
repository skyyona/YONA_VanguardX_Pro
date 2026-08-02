"""Real-Time P&L — 수익률 (%) 계산"""


class RealtimePnl:
    @staticmethod
    def calculate(initial_usdt: float, total_usdt: float) -> float:
        if initial_usdt <= 0:
            return 0.0
        return round(((total_usdt - initial_usdt) / initial_usdt) * 100.0, 4)
