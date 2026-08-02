"""
middle/models.py
중단 세션 모듈 데이터 모델
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class OHLCVBar:
    open_time:    int
    open:         float
    high:         float
    low:          float
    close:        float
    volume:       float        # base asset volume
    quote_volume: float        # USDT volume
    close_time:   int


@dataclass
class SymbolTicker:
    symbol:           str
    last_price:       float
    price_change:     float    # absolute price change
    price_change_pct: float    # 24h change %
    volume_usdt:      float    # 24h quote volume (USDT)
    high_24h:         float
    low_24h:          float


@dataclass
class FundingRateData:
    symbol:       str
    funding_rate: float        # e.g. 0.0001 = 0.01%
    funding_time: int


@dataclass
class OpenInterestData:
    symbol:        str
    open_interest: float       # in base asset (coins)
    timestamp:     int


@dataclass
class LongShortData:
    symbol:            str
    long_account_pct:  float   # % of accounts long  (0~100)
    short_account_pct: float   # % of accounts short (0~100)
    long_short_ratio:  float   # long / short
    timestamp:         int

