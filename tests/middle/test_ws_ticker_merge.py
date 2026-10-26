"""
tests/middle/test_ws_ticker_merge.py
시세 웹소켓 /market 경로 + !miniTicker@arr 부분 메시지 병합 5건.
Binance가 2026-04-23 구 /stream 경로를 폐지(연결은 되나 데이터 없음, 2026-10-26 실측).
miniTicker 메시지는 변경 심볼만 포함 → DataManager._on_ws_ticker_update가 기존 목록에 병합하고
REST와 같은 기준(TRADING 심볼)으로 정리. 네트워크 무의존(거래 심볼 집합만 대역).
"""
import sys
import types

_ws_stub = types.ModuleType("websocket")
_ws_stub.WebSocketApp = object
sys.modules.setdefault("websocket", _ws_stub)

from middle.data import websocket_ticker
from middle.data.data_manager import MiddleDataManager
from middle.data.websocket_klines import WebSocketKlines
from middle.models import SymbolTicker


def _tk(sym: str, price: float, vol: float) -> SymbolTicker:
    return SymbolTicker(sym, price, 0.0, 0.0, vol, price, price)


def _dm(trading: set) -> MiddleDataManager:
    dm = MiddleDataManager()
    dm._client = types.SimpleNamespace(_get_trading_symbols=lambda: trading)
    seed = [_tk("AUSDT", 1.0, 300.0), _tk("BUSDT", 2.0, 200.0), _tk("CUSDT", 3.0, 100.0)]
    dm._tkr_map = {t.symbol: t for t in seed}      # 시작 시 REST 전체 목록 역할
    dm._tickers = seed
    return dm


def test_streams_use_market_path():
    """캔들·티커 웹소켓 모두 /market/stream 경로 사용 (구 /stream 폐지)."""
    assert websocket_ticker._STREAM_URL == "wss://fstream.binance.com/market/stream?streams=!miniTicker@arr"
    k = WebSocketKlines.__new__(WebSocketKlines)
    k._symbol = "BTCUSDT"
    assert k._build_url().startswith("wss://fstream.binance.com/market/stream?streams=btcusdt@kline_1m")


def test_partial_message_is_merged_not_replacing():
    """변경 심볼만 담긴 메시지 → 나머지 심볼 유지, 해당 심볼만 갱신."""
    dm = _dm({"AUSDT", "BUSDT", "CUSDT"})
    dm._on_ws_ticker_update([_tk("CUSDT", 3.5, 500.0)])
    assert set(dm._tkr_map) == {"AUSDT", "BUSDT", "CUSDT"}
    assert dm._tkr_map["CUSDT"].last_price == 3.5
    assert dm._tkr_map["AUSDT"].last_price == 1.0


def test_volume_ranking_rebuilt_from_merged_list():
    """거래량 순위·정렬은 병합된 전체 목록 기준."""
    dm = _dm({"AUSDT", "BUSDT", "CUSDT"})
    dm._on_ws_ticker_update([_tk("CUSDT", 3.5, 500.0)])
    assert [t.symbol for t in dm._sorted_tickers] == ["CUSDT", "AUSDT", "BUSDT"]
    assert dm._vol_rank == {"CUSDT": 1, "AUSDT": 2, "BUSDT": 3}
    assert len(dm._tickers) == 3


def test_non_trading_symbols_are_pruned():
    """TRADING 집합에 없는 심볼(거래정지·상장폐지)은 병합 결과에서 제외 — REST 경로와 같은 기준."""
    dm = _dm({"AUSDT", "BUSDT", "DUSDT"})
    dm._on_ws_ticker_update([_tk("DUSDT", 4.0, 50.0), _tk("EUSDT", 5.0, 999.0)])
    assert set(dm._tkr_map) == {"AUSDT", "BUSDT", "DUSDT"}


def test_trading_set_unavailable_keeps_all():
    """TRADING 집합 조회 실패(빈 집합) → 정리 생략, 병합만 (REST 폴백과 같은 동작)."""
    dm = _dm(set())
    dm._on_ws_ticker_update([_tk("EUSDT", 5.0, 999.0)])
    assert set(dm._tkr_map) == {"AUSDT", "BUSDT", "CUSDT", "EUSDT"}
