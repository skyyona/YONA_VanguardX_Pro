"""
tests/middle/test_client_url_encoding.py
중단 Binance 클라이언트 — 한자 이름 심볼(예: 牛来USDT) URL 퍼센트 인코딩, ASCII URL은 그대로.
"""
import io
import json
import urllib.request

from middle.api.binance_client import MiddleBinanceClient


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch):
    sent = []
    def _urlopen(req, timeout=None):
        sent.append(req.full_url)
        return _Resp(json.dumps([]).encode())
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return sent


def test_non_ascii_symbol_is_percent_encoded(monkeypatch):
    sent = _capture(monkeypatch)
    MiddleBinanceClient().fetch_klines("牛来USDT", "1h", 3)
    # 기존: 요청 전 UnicodeEncodeError → 미전송(sent 비어 있음)
    assert sent == ["https://fapi.binance.com/fapi/v1/klines?symbol=%E7%89%9B%E6%9D%A5USDT&interval=1h&limit=3"]


def test_ascii_url_unchanged(monkeypatch):
    sent = _capture(monkeypatch)
    MiddleBinanceClient().fetch_klines("BTCUSDT", "15m", 200)
    assert sent == ["https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=200"]
