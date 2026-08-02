from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HeaderStatus(str, Enum):
    IDLE    = "idle"
    RUNNING = "running"
    ERROR   = "error"


class WalletQueryStatus(str, Enum):
    OK         = "ok"
    NO_API_KEY = "no_api_key"
    COMM_ERROR = "comm_error"


class TransferDirection(str, Enum):
    TO_FUTURES = "to_futures"
    TO_SPOT    = "to_spot"


@dataclass
class WalletBalanceResult:
    status:     WalletQueryStatus
    value_usdt: float


@dataclass
class PnlSnapshot:
    pnl_percent:            float
    pnl_amount_usdt:        float
    total_trading_value_usdt: float


@dataclass
class SessionSnapshot:
    kst_datetime_label:   str
    session_status_label: str
    volume_label:         str
    volume_hint:          str


@dataclass
class HeaderState:
    status:                    HeaderStatus
    initial_investment_usdt:   float
    pnl:                       PnlSnapshot
    session:                   SessionSnapshot
