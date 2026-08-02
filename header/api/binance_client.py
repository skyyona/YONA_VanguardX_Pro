"""
header/api/binance_client.py
헤더 모듈 전용 바이낸스 REST 클라이언트
잔고 조회·자금 이체·BTC 거래량 비율 API 호출
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

from header.models import WalletBalanceResult, WalletQueryStatus


class HeaderBinanceClient:
    _FUTURES_BASE_URL = "https://fapi.binance.com"
    _SPOT_BASE_URL    = "https://api.binance.com"

    def __init__(self) -> None:
        env_path = Path(__file__).resolve().parents[1] / ".env"  # header/.env
        env = self._load_env(env_path)
        self._api_key    = env.get("HEADER_BINANCE_API_KEY", "")
        self._api_secret = env.get("HEADER_BINANCE_API_SECRET", "")

    # ── 잔고 조회 ──────────────────────────────────────────────
    def fetch_futures_total_balance_with_status(self) -> WalletBalanceResult:
        if not self._api_key or not self._api_secret:
            return WalletBalanceResult(WalletQueryStatus.NO_API_KEY, 0.0)
        val = self._fetch_live_total()
        if val is None:
            return WalletBalanceResult(WalletQueryStatus.COMM_ERROR, 0.0)
        return WalletBalanceResult(WalletQueryStatus.OK, max(0.0, val))

    def fetch_spot_usdt_balance(self) -> WalletBalanceResult:
        if not self._api_key or not self._api_secret:
            return WalletBalanceResult(WalletQueryStatus.NO_API_KEY, 0.0)
        payload = self._signed_get(self._SPOT_BASE_URL, "/api/v3/account")
        if payload is None:
            return WalletBalanceResult(WalletQueryStatus.COMM_ERROR, 0.0)
        for b in payload.get("balances", []):
            if b.get("asset") == "USDT":
                return WalletBalanceResult(WalletQueryStatus.OK, max(0.0, float(b.get("free", 0.0))))
        return WalletBalanceResult(WalletQueryStatus.OK, 0.0)

    def fetch_futures_available_balance(self) -> WalletBalanceResult:
        if not self._api_key or not self._api_secret:
            return WalletBalanceResult(WalletQueryStatus.NO_API_KEY, 0.0)
        payload = self._signed_get(self._FUTURES_BASE_URL, "/fapi/v2/account")
        if payload is None:
            return WalletBalanceResult(WalletQueryStatus.COMM_ERROR, 0.0)
        return WalletBalanceResult(WalletQueryStatus.OK, max(0.0, float(payload.get("availableBalance", 0.0))))

    # ── 자금 이체 ──────────────────────────────────────────────
    def transfer_spot_to_futures(self, amount_usdt: float) -> bool:
        return self._universal_transfer("MAIN_UMFUTURE", amount_usdt)

    def transfer_futures_to_spot(self, amount_usdt: float) -> bool:
        return self._universal_transfer("UMFUTURE_MAIN", amount_usdt)

    # ── BTC 거래량 비율 ────────────────────────────────────────
    def fetch_btc_volume_ratio(self) -> float:
        try:
            url = f"{self._FUTURES_BASE_URL}/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=169"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            volumes = [float(k[5]) for k in data]
            open_time_ms  = int(data[-1][0])
            now_ms        = int(time.time() * 1000)
            elapsed_ratio = min((now_ms - open_time_ms) / 3_600_000, 1.0)
            current_vol   = volumes[-1] / elapsed_ratio if elapsed_ratio >= 0.05 else volumes[-2]
            same_hour = [volumes[-(1 + 24 * n)] for n in range(1, 8) if (1 + 24 * n) <= len(volumes)]
            if not same_hour:
                return 1.0
            avg = sum(same_hour) / len(same_hour)
            return current_vol / avg if avg > 0 else 1.0
        except Exception as e:
            logging.warning("fetch_btc_volume_ratio: %s", e)
            return 1.0

    # ── 내부 헬퍼 ──────────────────────────────────────────────
    def _fetch_live_total(self) -> float | None:
        payload = self._signed_get(self._FUTURES_BASE_URL, "/fapi/v2/account")
        if payload is None:
            return None
        return float(payload.get("totalWalletBalance", 0.0))

    def _signed_get(self, base_url: str, path: str) -> dict | None:
        try:
            timestamp    = int(time.time() * 1000)
            params       = {"timestamp": str(timestamp)}
            query_string = urllib.parse.urlencode(params)
            signature    = hmac.new(
                self._api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            url = f"{base_url}{path}?{query_string}&signature={signature}"
            req = urllib.request.Request(url, headers={"X-MBX-APIKEY": self._api_key}, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.warning("_signed_get %s%s: %s", base_url, path, e)
            return None

    def _universal_transfer(self, transfer_type: str, amount_usdt: float) -> bool:
        if not self._api_key or not self._api_secret:
            return False
        try:
            timestamp    = int(time.time() * 1000)
            params       = {"type": transfer_type, "asset": "USDT",
                            "amount": f"{amount_usdt:.8f}", "timestamp": str(timestamp)}
            query_string = urllib.parse.urlencode(params)
            signature    = hmac.new(
                self._api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            url = f"{self._SPOT_BASE_URL}/sapi/v1/asset/transfer?{query_string}&signature={signature}"
            req = urllib.request.Request(url, headers={"X-MBX-APIKEY": self._api_key}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read().decode("utf-8"))
            return True
        except Exception as e:
            logging.warning("_universal_transfer %s %.2fUSDT: %s", transfer_type, amount_usdt, e)
            return False

    @staticmethod
    def _load_env(path: Path) -> dict[str, str]:
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
