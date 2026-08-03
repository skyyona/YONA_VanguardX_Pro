"""
middle/api/binance_client.py
중단 모듈 전용 바이낸스 REST 클라이언트 (시장 데이터 전용)

Rate Limit (USDⓈ-M Futures):
  REQUEST_WEIGHT = 2,400 / 분, IP 기준 적용.
  API 키를 넣어도 이 한도는 상향되지 않는다.
  (6,000 weight/분은 Spot API 수치이며 선물에는 해당하지 않는다.)

공개 엔드포인트(ticker, klines, funding, OI, L/S ratio)만 사용하므로
서명(HMAC)은 불필요. X-MBX-APIKEY 헤더는 사용량 추적 목적으로만 유지한다.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

_FUTURES_BASE = "https://fapi.binance.com"
_SPOT_BASE    = "https://api.binance.com"

_TRADING_CACHE_TTL = 300   # TRADING 심볼 캐시 유효 기간 (초, 5분)

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(path: Path) -> dict[str, str]:
    """middle/.env 파일에서 키·시크릿 로드."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


class MiddleBinanceClient:
    """중단 모듈 전용 바이낸스 REST 클라이언트.

    middle/.env 에 MIDDLE_BINANCE_API_KEY 가 설정되면
    모든 공개 API 요청에 X-MBX-APIKEY 헤더를 추가합니다.
    선물 REST 한도는 IP 기준 2,400 weight/분으로 고정이며 키로 상향되지 않습니다.
    """

    def __init__(self) -> None:
        env = _load_env(_ENV_PATH)
        self._api_key = env.get("MIDDLE_BINANCE_API_KEY", "")
        self._trading_symbols:    set[str] = set()
        self._trading_cache_ts:   float    = 0.0

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    def _get(self, url: str, timeout: int = 8) -> dict | list | None:
        """API 키 있으면 X-MBX-APIKEY 헤더 포함 GET 요청."""
        try:
            headers = {}
            if self._api_key:
                headers["X-MBX-APIKEY"] = self._api_key
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    # ── TRADING 심볼 캐시 ─────────────────────────────────────
    def _get_trading_symbols(self) -> set[str]:
        """exchange_info 기반 TRADING 상태 심볼 집합 반환 (5분 캐시).

        캐시가 유효하면 API 추가 호출 없이 캐시 반환.
        캐시 만료 또는 최초 호출 시에만 fetch_exchange_info() 를 호출.
        """
        now = time.time()
        if self._trading_symbols and (now - self._trading_cache_ts) < _TRADING_CACHE_TTL:
            return self._trading_symbols
        ei = self.fetch_exchange_info()
        if ei:
            syms = {
                s["symbol"]
                for s in ei.get("symbols", [])
                if s.get("status") == "TRADING"
            }
            if syms:
                self._trading_symbols  = syms
                self._trading_cache_ts = now
        return self._trading_symbols

    # ── 24h Ticker ────────────────────────────────────────────
    def fetch_all_tickers(self) -> list[dict]:
        """USDT 영구 선물 전체 24h ticker 반환 (TRADING 심볼만).

        exchange_info 기반 TRADING 필터를 적용하여 거래정지·상장폐지
        예정 심볼을 랭킹 풀에서 제외한다. exchange_info는 5분 캐시로
        관리되므로 빈번한 호출에서도 추가 API 비용이 최소화된다.
        exchange_info 조회 실패 시 USDT 접미사 필터만 적용(폴백).
        """
        data = self._get(f"{_FUTURES_BASE}/fapi/v1/ticker/24hr")
        if not isinstance(data, list):
            return []
        trading = self._get_trading_symbols()
        if trading:
            return [
                d for d in data
                if isinstance(d, dict)
                and d.get("symbol", "").endswith("USDT")
                and d.get("symbol") in trading
            ]
        # exchange_info 실패 시 폴백: 기존 USDT 접미사 필터만 적용
        return [d for d in data if isinstance(d, dict) and d.get("symbol", "").endswith("USDT")]

    def fetch_ticker(self, symbol: str) -> dict | None:
        """단일 심볼 24h ticker."""
        data = self._get(f"{_FUTURES_BASE}/fapi/v1/ticker/24hr?symbol={symbol}")
        return data if isinstance(data, dict) else None

    # ── OHLCV (Klines) ────────────────────────────────────────
    def fetch_klines(self, symbol: str, interval: str, limit: int = 100) -> list[list]:
        """OHLCV 캔들 데이터."""
        url = f"{_FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        data = self._get(url)
        return data if isinstance(data, list) else []

    # ── Funding Rate ──────────────────────────────────────────
    def fetch_latest_funding_rate(self, symbol: str) -> dict | None:
        """최신 펀딩비 1건 반환."""
        url = f"{_FUTURES_BASE}/fapi/v1/fundingRate?symbol={symbol}&limit=1"
        data = self._get(url)
        if isinstance(data, list) and data:
            return data[-1]
        return None

    def fetch_funding_rate_history(self, symbol: str, limit: int = 8) -> list[dict]:
        """펀딩비 이력 N건."""
        url = f"{_FUTURES_BASE}/fapi/v1/fundingRate?symbol={symbol}&limit={limit}"
        data = self._get(url)
        return data if isinstance(data, list) else []

    # ── Open Interest ─────────────────────────────────────────
    def fetch_open_interest(self, symbol: str) -> dict | None:
        """현재 미결제약정."""
        url = f"{_FUTURES_BASE}/fapi/v1/openInterest?symbol={symbol}"
        return self._get(url)

    def fetch_open_interest_hist(self, symbol: str, period: str = "5m", limit: int = 10) -> list[dict]:
        """미결제약정 이력 (OI 변화율 계산용)."""
        url = (f"{_FUTURES_BASE}/futures/data/openInterestHist"
               f"?symbol={symbol}&period={period}&limit={limit}")
        data = self._get(url)
        return data if isinstance(data, list) else []

    # ── Long/Short Ratio ──────────────────────────────────────
    def fetch_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 1) -> list[dict]:
        """계좌 기준 롱/숏 비율."""
        url = (f"{_FUTURES_BASE}/futures/data/globalLongShortAccountRatio"
               f"?symbol={symbol}&period={period}&limit={limit}")
        data = self._get(url)
        return data if isinstance(data, list) else []

    def fetch_taker_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 1) -> list[dict]:
        """거래량 기준 롱/숏 비율 (매수/매도 체결량)."""
        url = (f"{_FUTURES_BASE}/futures/data/takerlongshortRatio"
               f"?symbol={symbol}&period={period}&limit={limit}")
        data = self._get(url)
        return data if isinstance(data, list) else []

    # ── Exchange Info ─────────────────────────────────────────
    def fetch_exchange_info(self) -> dict | None:
        """거래소 심볼 목록 및 신규 상장 정보."""
        return self._get(f"{_FUTURES_BASE}/fapi/v1/exchangeInfo")

    # ── BTC 마크가격 ──────────────────────────────────────────
    def fetch_mark_price(self, symbol: str) -> dict | None:
        """마크가격 + 인덱스가격."""
        url = f"{_FUTURES_BASE}/fapi/v1/premiumIndex?symbol={symbol}"
        return self._get(url)

