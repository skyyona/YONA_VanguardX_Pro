"""
bottom/api/binance_client.py
하단 전용 바이낸스 REST 클라이언트 (주문 실행용)
bottom/.env에 API 키 설정 후 실제 Binance Futures 주문 전송.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bottom.models import Order, OrderResult, OrderSide, OrderType

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_FUTURES_BASE = "https://fapi.binance.com"


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


class BottomBinanceClient:
    """하단 거래 엔진 전용 Binance REST 클라이언트 (Binance Futures 실거래 전용)."""

    def __init__(self) -> None:
        env = _load_env(_ENV_PATH)
        self._api_key    = env.get("BOTTOM_BINANCE_API_KEY", "")
        self._api_secret = env.get("BOTTOM_BINANCE_API_SECRET", "")
        self._has_keys   = bool(self._api_key and self._api_secret)
        self._precision_cache:  dict[str, int]   = {}
        self._min_qty_cache:    dict[str, float] = {}
        self._tick_size_cache:  dict[str, float] = {}
        self._step_size_cache:  dict[str, float] = {}
        self._last_api_error:   str              = ""
        self._rate_limited_until: float          = 0.0
        self._time_offset:      float            = 0.0
        self._sync_server_time()

    @property
    def is_live(self) -> bool:
        """API 키가 설정되어 실거래 가능한 상태인지 반환."""
        return self._has_keys

    # ── 레버리지 설정 ─────────────────────────────────────────────
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            params = {"symbol": symbol, "leverage": str(leverage),
                      "timestamp": str(self._ts())}
            return self._signed_post("/fapi/v1/leverage", params) is not None
        except Exception:
            return False

    # ── 마진 타입 설정 ────────────────────────────────────────────
    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """-4046(이미 동일 타입)은 성공으로 처리."""
        try:
            params = {"symbol": symbol, "marginType": margin_type,
                      "timestamp": str(self._ts())}
            result = self._signed_post("/fapi/v1/marginType", params)
            if result is not None:
                return True
            if "-4046" in self._last_api_error:
                return True
            return False
        except Exception:
            return False

    # ── 주문 실행 ─────────────────────────────────────────────────
    def place_order(self, order: Order, mark: float = 0.0) -> OrderResult:
        """주문 실행. mark: 호출자가 이미 조회한 마크가격 (REST 중복 방지)."""
        return self._live_order(order, mark)

    def close_position(self, symbol: str, side: str, quantity: float,
                       mark: float = 0.0) -> OrderResult:
        """포지션 청산 주문."""
        close_side = "SELL" if side == "long" else "BUY"
        order = Order(
            symbol=symbol,
            side=OrderSide(close_side),
            order_type=OrderType.MARKET,
            quantity=quantity,
        )
        return self.place_order(order, mark)

    def place_stop_market(self, symbol: str, side: str,
                          stop_price: float) -> str:
        """STOP_MARKET SL 주문 등록 (Binance UI TP/SL 표시용, closePosition=true).
        side: "SELL"(롱SL) / "BUY"(숏SL). 성공 시 orderId 문자열, 실패 시 ""."""
        if not self._has_keys or stop_price <= 0:
            return ""
        try:
            params = {
                "symbol":           symbol,
                "side":             side,
                "type":             "STOP_MARKET",
                "stopPrice":        f"{stop_price:.8f}",
                "closePosition":    "true",
                "newClientOrderId": f"sl_{uuid.uuid4().hex[:20]}",
                "timestamp":        str(self._ts()),
            }
            result = self._signed_post("/fapi/v1/order", params)
            return str(result.get("orderId", "")) if result else ""
        except Exception:
            return ""

    def place_trailing_stop(self, symbol: str, side: str,
                            callback_rate: float, quantity: float) -> str:
        """TRAILING_STOP_MARKET 주문 등록 (Phase3 잔여 수량 보호용).
        side: "SELL"(롱) / "BUY"(숏). 성공 시 orderId 문자열, 실패 시 ""."""
        if not self._has_keys or quantity <= 0 or not (0.1 <= callback_rate <= 10.0):
            return ""
        try:
            prec   = self.get_qty_precision(symbol)
            params = {
                "symbol":           symbol,
                "side":             side,
                "type":             "TRAILING_STOP_MARKET",
                "callbackRate":     f"{callback_rate:.1f}",
                "quantity":         f"{quantity:.{prec}f}",
                "reduceOnly":       "true",
                "newClientOrderId": f"tr_{uuid.uuid4().hex[:20]}",
                "timestamp":        str(self._ts()),
            }
            result = self._signed_post("/fapi/v1/order", params)
            return str(result.get("orderId", "")) if result else ""
        except Exception:
            return ""

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """등록된 SL/Trailing 주문 취소. 성공 또는 이미 체결·취소된 경우 True."""
        if not self._has_keys or not order_id:
            return False
        if self._rate_limited_until > time.time():
            return False
        try:
            params = {
                "symbol":    symbol,
                "orderId":   order_id,
                "timestamp": str(self._ts()),
            }
            qs  = urllib.parse.urlencode(params)
            sig = hmac.new(self._api_secret.encode(), qs.encode(),
                           hashlib.sha256).hexdigest()
            url = f"{_FUTURES_BASE}/fapi/v1/order?{qs}&signature={sig}"
            req = urllib.request.Request(
                url, method="DELETE",
                headers={"X-MBX-APIKEY": self._api_key},
            )
            with urllib.request.urlopen(req, timeout=8):
                return True
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
                code = body.get("code", 0)
                if code == -2011:
                    return True
                self._last_api_error = f"cancel_order [{code}] {body.get('msg', str(e))}"
            except Exception:
                self._last_api_error = f"cancel_order HTTP {e.code}"
            if e.code == 429:
                try:
                    retry_after = int(e.headers.get("Retry-After") or 60)
                except (ValueError, TypeError):
                    retry_after = 60
                self._rate_limited_until = time.time() + max(retry_after, 10)
            elif e.code == 418:
                self._rate_limited_until = time.time() + 300
                self._last_api_error = "[긴급] Binance IP 차단(418) — 5분 후 자동 해제. API 호출 즉시 중단 필요"
            return False
        except Exception as e:
            self._last_api_error = f"cancel_order {e}"
            return False

    # ── 심볼 정보 ─────────────────────────────────────────────────
    def get_qty_precision(self, symbol: str) -> int:
        """LOT_SIZE stepSize 기반 수량 소수 자릿수 반환. 공개 API(키 불필요). 실패 시 6 반환."""
        if symbol in self._precision_cache:
            return self._precision_cache[symbol]
        try:
            url = f"{_FUTURES_BASE}/fapi/v1/exchangeInfo?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for sym_info in data.get("symbols", []):
                if sym_info.get("symbol") == symbol:
                    for f in sym_info.get("filters", []):
                        ft = f.get("filterType")
                        if ft == "LOT_SIZE":
                            step = f.get("stepSize", "0.000001")
                            prec = len(step.rstrip("0").split(".")[-1]) if "." in step else 0
                            self._precision_cache[symbol] = prec
                            self._min_qty_cache[symbol]   = float(f.get("minQty", "0"))
                            self._step_size_cache[symbol] = float(step)
                        elif ft == "PRICE_FILTER":
                            self._tick_size_cache[symbol] = float(f.get("tickSize", "0.01"))
                    break
        except Exception:
            pass
        if symbol not in self._precision_cache:
            self._precision_cache[symbol] = 6
        return self._precision_cache[symbol]

    def floor_qty(self, symbol: str, qty: float) -> float:
        """stepSize 배수로 내림 정렬 (Binance LOT_SIZE 요건 충족)."""
        import math
        if symbol not in self._step_size_cache:
            self.get_qty_precision(symbol)
        step = self._step_size_cache.get(symbol, 0.0)
        if step <= 0:
            return 0.0
        return math.floor(qty / step) * step

    def get_price_precision(self, symbol: str) -> float:
        """PRICE_FILTER tickSize 반환 (stopPrice 반올림 기준). 실패 시 0.01."""
        if symbol not in self._tick_size_cache:
            self.get_qty_precision(symbol)
        return self._tick_size_cache.get(symbol, 0.01)

    def get_min_qty(self, symbol: str) -> float:
        """LOT_SIZE minQty 반환. 캐시 미스 시 get_qty_precision() 호출로 채움. 실패 시 0.0."""
        if symbol not in self._min_qty_cache:
            self.get_qty_precision(symbol)
        return self._min_qty_cache.get(symbol, 0.0)

    # ── 계좌 조회 ─────────────────────────────────────────────────
    def get_position(self, symbol: str) -> dict | None:
        """현재 포지션 조회."""
        try:
            payload = self._signed_get("/fapi/v2/positionRisk",
                                       {"symbol": symbol})
            if isinstance(payload, list) and payload:
                return payload[0]
        except Exception:
            pass
        return None

    def get_mark_price(self, symbol: str) -> float | None:
        """마크가격 조회 (SL/TP 평가용)."""
        try:
            url = f"{_FUTURES_BASE}/fapi/v1/premiumIndex?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return float(data.get("markPrice", 0)) or None
        except Exception:
            return None

    def get_open_orders(self, symbol: str) -> "list | None":
        """미체결 주문 목록 조회 (SL order_id 복구용). 성공 시 list, API 실패 시 None."""
        if not self._has_keys:
            return []
        try:
            result = self._signed_get("/fapi/v1/openOrders", {"symbol": symbol})
            return result if isinstance(result, list) else None
        except Exception:
            return None

    def get_account_balance(self) -> "float | None":
        """USDT Futures 총 잔고 조회(walletBalance). API 키 미설정·통신 오류 시 None 반환."""
        if not self._has_keys:
            return None
        try:
            payload = self._signed_get("/fapi/v2/account")
            if isinstance(payload, dict):
                for asset in payload.get("assets", []):
                    if asset.get("asset") == "USDT":
                        return float(asset.get("walletBalance", 0.0))
                return 0.0   # USDT 항목 없음 = 잔고 0 (API 통신은 성공)
            return None
        except Exception:
            return None

    def is_one_way_mode(self) -> "bool | None":
        """포지션 모드 조회. True=단방향(정상), False=헤지모드(불가), None=조회실패."""
        if not self._has_keys:
            return None
        try:
            result = self._signed_get("/fapi/v1/positionSide/dual")
            if isinstance(result, dict):
                return not result.get("dualSidePosition", True)
            return None
        except Exception:
            return None

    def get_leverage_bracket(self, symbol: str) -> "int | None":
        """레버리지 브래킷 조회. 노셔널 0 구간의 최대 레버리지(initialLeverage) 반환. 실패 시 None."""
        if not self._has_keys:
            return None
        try:
            result = self._signed_get("/fapi/v1/leverageBracket", {"symbol": symbol})
            if isinstance(result, list) and result:
                brackets = result[0].get("brackets", [])
                if brackets:
                    return int(brackets[0]["initialLeverage"])
            return None
        except Exception:
            return None

    # ── 내부 헬퍼 ────────────────────────────────────────────────
    def _live_order(self, order: Order, mark: float = 0.0) -> OrderResult:
        """실제 Binance Futures 주문 전송."""
        try:
            prec = self.get_qty_precision(order.symbol)
            params = {
                "symbol":           order.symbol,
                "side":             order.side.value,
                "type":             order.order_type.value,
                "quantity":         f"{order.quantity:.{prec}f}",
                "newClientOrderId": f"yv_{uuid.uuid4().hex[:20]}",
                "timestamp":        str(self._ts()),
            }
            if order.order_type == OrderType.LIMIT and order.price:
                params["price"]       = f"{order.price:.8f}"
                params["timeInForce"] = "GTC"
            result = self._signed_post("/fapi/v1/order", params)
            if not result:
                return OrderResult(False, error=self._last_api_error or "API 응답 없음")
            avg_p  = float(result.get("avgPrice") or 0)
            prc_p  = float(result.get("price")    or 0)
            fill   = avg_p if avg_p > 0 else prc_p
            if fill <= 0 and mark > 0:
                fill = mark
            qty_filled = float(result.get("executedQty", order.quantity))
            if qty_filled <= 0:
                return OrderResult(False, error="executedQty=0 — 체결 수량 없음")
            return OrderResult(
                success=True,
                order_id=str(result.get("orderId", "")),
                fill_price=fill,
                quantity=qty_filled,
            )
        except Exception as e:
            return OrderResult(False, error=str(e))

    def _signed_get(self, path: str, extra_params: dict | None = None) -> dict | list | None:
        if self._rate_limited_until > time.time():
            self._last_api_error = f"Rate Limited — {int(self._rate_limited_until - time.time())}초 후 해제"
            return None
        params = {"timestamp": str(self._ts())}
        if extra_params:
            params.update(extra_params)
        qs  = urllib.parse.urlencode(params)
        sig = hmac.new(self._api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        url = f"{_FUTURES_BASE}{path}?{qs}&signature={sig}"
        self._last_api_error = ""
        try:
            req = urllib.request.Request(url, headers={"X-MBX-APIKEY": self._api_key})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                self._last_api_error = f"[{body.get('code', e.code)}] {body.get('msg', str(e))}"
            except Exception:
                self._last_api_error = f"HTTP {e.code}: {e.reason}"
            if e.code == 429:
                try:
                    retry_after = int(e.headers.get("Retry-After") or 60)
                except (ValueError, TypeError):
                    retry_after = 60
                self._rate_limited_until = time.time() + max(retry_after, 10)
            elif e.code == 418:
                self._rate_limited_until = time.time() + 300
                self._last_api_error = "[긴급] Binance IP 차단(418) — 5분 후 자동 해제. API 호출 즉시 중단 필요"
            elif e.code == 503:
                self._last_api_error = "[주의] Binance 503 — 서버 일시 과부하. 잠시 후 재시도 가능"
            return None
        except Exception as e:
            self._last_api_error = str(e)
            return None

    def _signed_post(self, path: str, params: dict) -> dict | None:
        if self._rate_limited_until > time.time():
            self._last_api_error = f"Rate Limited — {int(self._rate_limited_until - time.time())}초 후 해제"
            return None
        qs  = urllib.parse.urlencode(params)
        sig = hmac.new(self._api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        body = (qs + f"&signature={sig}").encode("utf-8")
        url  = f"{_FUTURES_BASE}{path}"
        self._last_api_error = ""
        try:
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"X-MBX-APIKEY": self._api_key,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body_err = json.loads(e.read().decode("utf-8"))
                self._last_api_error = f"[{body_err.get('code', e.code)}] {body_err.get('msg', str(e))}"
                if body_err.get("code") == -1008:
                    self._last_api_error = "[경보] Binance 서버 과부하(-1008) — 재시도 가능"
            except Exception:
                self._last_api_error = f"HTTP {e.code}: {e.reason}"
            if e.code == 429:
                try:
                    retry_after = int(e.headers.get("Retry-After") or 60)
                except (ValueError, TypeError):
                    retry_after = 60
                self._rate_limited_until = time.time() + max(retry_after, 10)
            elif e.code == 418:
                self._rate_limited_until = time.time() + 300
                self._last_api_error = "[긴급] Binance IP 차단(418) — 5분 후 자동 해제. API 호출 즉시 중단 필요"
            elif e.code == 503:
                self._last_api_error = "[주의] Binance 503 — 주문 체결 여부 불명확. 포지션 확인 필요"
            return None
        except Exception as e:
            self._last_api_error = str(e)
            return None

    def _sync_server_time(self) -> None:
        try:
            url = f"{_FUTURES_BASE}/fapi/v1/time"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            server_time = data["serverTime"]
            self._time_offset = (server_time - int(time.time() * 1000)) / 1000.0
        except Exception:
            self._time_offset = 0.0

    def _ts(self) -> int:
        return int((time.time() + self._time_offset) * 1000)

