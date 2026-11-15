"""
tests/test_rate_gate_clients.py
공통 차단 장치 연결 확인 (2026-11-15) — 실제 클라이언트 3곳(중단·하단·헤더)이 429 한 번 뒤 네트워크로 보내지 않는지,
하단 엔진 진입 재시도 판정이 '재시도 안 함' 경로를 타는지. 네트워크 없이 urlopen 대역.
"""
import http.client
import io
import json
import logging
import urllib.error
import urllib.request

import pytest

import core.rate_gate as rg
from middle.api.binance_client import MiddleBinanceClient
from bottom_engine.api.binance_client import BottomBinanceClient
from header.api.binance_client import HeaderBinanceClient


class _Resp:
    def __init__(self, body=b"[]"):
        self._b = body
        self.status = 200
        self.headers = http.client.HTTPMessage()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def net(monkeypatch, tmp_path):
    """첫 바이낸스 요청 = 429 (Retry-After 60), 그 뒤는 정상 응답. calls = 실제로 '네트워크로 나간' 요청."""
    calls = []

    def fake(url, *a, **k):
        u = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        calls.append(u)
        if len(calls) == 1:
            h = http.client.HTTPMessage(); h["Retry-After"] = "60"
            raise urllib.error.HTTPError(u, 429, "Too Many Requests", h, io.BytesIO(b'{"code":-1003,"msg":"x"}'))
        return _Resp(json.dumps({"serverTime": 0}).encode() if "/time" in u else b"[]")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    root = logging.getLogger()
    before = list(root.filters)
    gate = rg.install(tmp_path / "rate_gate.json")
    yield calls, gate
    root.filters[:] = before
    for h in root.handlers:
        h.filters[:] = [x for x in h.filters if not isinstance(x, rg._DropBlockedLogs)]
    monkeypatch.setattr(rg, "_gate", None)


def test_middle_client_stops_after_429(net):
    calls, gate = net
    cl = MiddleBinanceClient()
    assert cl.fetch_klines("BTCUSDT", "5m", 3) == []           # 429 — 기존처럼 빈 결과
    assert gate.remaining() > 59
    assert cl.fetch_klines("ETHUSDT", "5m", 3) == []
    assert cl.fetch_all_book_tickers() == []
    assert len(calls) == 1                                        # 뒤 요청은 네트워크 미전송


def test_bottom_client_public_and_signed_calls_stop(net):
    calls, gate = net
    cl = BottomBinanceClient()                                   # 생성 시 서버 시간 조회 1회 = 429
    n = len(calls)
    assert gate.remaining() > 59
    assert cl.get_mark_price("BTCUSDT") is None                  # 공개 조회 (기존 하단 자체 차단 미적용 경로)
    assert cl._signed_get("/fapi/v2/positionRisk", {}) is None if cl._has_keys else True
    assert len(calls) == n
    if cl._has_keys:
        err = cl._last_api_error
        # trading_engine 진입 재시도 판정: 'Rate Limited' → 재주문·포지션 확인 경로 안 탐
        assert "Rate Limited" in err and "URLError" not in err and "timed out" not in err and "503" not in err


def test_header_client_stops(net):
    calls, gate = net
    cl = HeaderBinanceClient()
    assert cl.fetch_btc_volume_ratio() == 1.0                    # 429 — 기존 실패값
    assert cl.fetch_btc_volume_ratio() == 1.0
    assert len(calls) == 1
