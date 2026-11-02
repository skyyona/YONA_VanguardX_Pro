"""
tests/middle/test_pending_settling.py
1열 Pending Listing(PENDING_TRADING 상장 예정) · Blacklist 탭 Settling(비정상 상태) 감지 결과 고정.
조회(MiddleDataManager.fetch_pending_listings·fetch_exchange_info) → 변환(PendingListingDetector.parse·SettlingDetector.detect).
exchangeInfo·premiumIndex 응답은 대역 클라이언트로 공급 — 네트워크 없음.
"""
from middle.col1_ranking_blacklist.ranking.pending_listing import PendingEntry, PendingListingDetector
from middle.data.data_manager import MiddleDataManager
from middle.data.settling import SettlingDetector, SettlingEntry

_INFO = {"symbols": [
    {"symbol": "AAAUSDT", "status": "PENDING_TRADING", "baseAsset": "AAA", "onboardDate": 300,
     "underlyingType": "COIN", "underlyingSubType": ["DeFi"]},
    {"symbol": "BBBUSDT", "status": "PENDING_TRADING", "baseAsset": "BBB", "onboardDate": 100,
     "underlyingType": "EQUITY", "underlyingSubType": ["TradFi"]},
    {"symbol": "CCCUSDT", "status": "TRADING", "onboardDate": 50},
    {"symbol": "DDDUSDC", "status": "PENDING_TRADING", "onboardDate": 10},
    {"symbol": "EEEUSDT", "status": "SETTLING"},
    {"symbol": "FFFUSDT", "status": "BREAK"},
    {"symbol": "GGGUSDT", "status": "DELIVERED"},
    {"symbol": "HHHUSDC", "status": "SETTLING"},
]}


class _Client:
    """MiddleBinanceClient 대역 — 조회 순서 기록."""

    def __init__(self, info, marks):
        self.info, self.marks, self.calls = info, marks, []

    def fetch_exchange_info(self):
        self.calls.append("exchangeInfo")
        return self.info

    def fetch_mark_price(self, sym):
        self.calls.append(sym)
        return self.marks.get(sym)


def _dm(client) -> MiddleDataManager:
    """조회 메서드만 쓰는 MiddleDataManager — __init__(WS·스레드) 없이 클라이언트만 연결."""
    dm = MiddleDataManager.__new__(MiddleDataManager)
    dm._client = client
    return dm


def test_pending_entries_sorted_with_mark_prices():
    client = _Client(_INFO, {"AAAUSDT": {"markPrice": "1.5"}})
    entries = PendingListingDetector.parse(_dm(client).fetch_pending_listings())
    assert entries == [
        PendingEntry("BBBUSDT", "BBB", 100, "EQUITY", ["TradFi"], 0.0),   # markPrice 조회 실패 → 0.0
        PendingEntry("AAAUSDT", "AAA", 300, "COIN", ["DeFi"], 1.5),
    ]
    assert client.calls == ["exchangeInfo", "BBBUSDT", "AAAUSDT"]   # 1회 + 심볼당 1회, 상장 시각 순


def test_pending_exchange_info_failure_is_none():
    """exchangeInfo 실패 → None (상장 예정 없음 []과 구분 — 1열에 '조회 실패' 표시)."""
    client = _Client(None, {})
    assert _dm(client).fetch_pending_listings() is None
    assert client.calls == ["exchangeInfo"]


def test_settling_entries():
    assert SettlingDetector.detect(_dm(_Client(_INFO, {})).fetch_exchange_info()) == [
        SettlingEntry("EEEUSDT", "SETTLING", "SETTLING", "settling"),
        SettlingEntry("FFFUSDT", "BREAK", "HALT", "halt"),
        SettlingEntry("GGGUSDT", "DELIVERED", "DELISTED", "warning"),
    ]
