"""
tests/middle/test_funding_cache.py
정산 펀딩비 재사용 (2026-11-08): fundingRate?limit=1(정산 값) 그대로, 다음 정산 전에는 재조회 생략.
 - 창 = premiumIndex nextFundingTime − fundingInfo 간격 ~ nextFundingTime
 - 정산 직후 새 값 미게시 → 재조회 반복 / 간격 모름(fundingInfo 없음) → 매번 조회 / premiumIndex 실패 → 매번 조회
 - STAGE2·상세 갱신 같은 저장 값 사용
네트워크 조회만 대역, 실제 MiddleDataManager 함수 실행.
"""
import time

import middle.data.data_manager as dm_mod
from middle.data.data_manager import MiddleDataManager
from middle.models import FundingRateData, SymbolTicker, LongShortData
from bottom_engine.models import StrategyParams

_H = 3_600_000


class _FR:
    """정산 기록 대역 — settled[sym] = (값, 정산 시각 ms), 호출 횟수 기록."""
    def __init__(self, settled):
        self.settled, self.calls = settled, []

    def fetch(self, sym):
        self.calls.append(sym)
        v = self.settled.get(sym)
        return FundingRateData(sym, v[0], v[1]) if v else None


class _Client:
    def __init__(self, premium, info):
        self.premium, self.info, self.calls = premium, info, []

    def fetch_all_premium_index(self):
        self.calls.append("premiumIndex")
        return self.premium

    def fetch_funding_info(self):
        self.calls.append("fundingInfo")
        return self.info


def _dm(monkeypatch, settled, premium, info):
    monkeypatch.setattr(dm_mod.StrategyLoader, "load_or_default",
                        staticmethod(lambda m: StrategyParams(sort_mode=m)))
    dm = MiddleDataManager()
    dm._fr_svc = _FR(settled)
    dm._client = _Client(premium, info)
    return dm


def _now_hour():
    return int(time.time() * 1000) // _H * _H


def test_reuse_until_next_settlement(monkeypatch):
    last = _now_hour()
    dm = _dm(monkeypatch, {"AUSDT": (0.0001, last)},
             [{"symbol": "AUSDT", "nextFundingTime": last + 4 * _H}],
             [{"symbol": "AUSDT", "fundingIntervalHours": 4}])
    dm._refresh_funding_window()
    assert dm._fr_window["AUSDT"] == (last, last + 4 * _H)
    a, b = dm._get_funding("AUSDT"), dm._get_funding("AUSDT")
    assert a.funding_rate == b.funding_rate == 0.0001
    assert dm._fr_svc.calls == ["AUSDT"]            # 두 번째는 저장 값


def test_refetch_after_next_settlement_time_passes(monkeypatch):
    last = _now_hour() - 4 * _H
    dm = _dm(monkeypatch, {"AUSDT": (0.0001, last)},
             [{"symbol": "AUSDT", "nextFundingTime": last + 4 * _H - 1}],   # 다음 정산 시각이 이미 지남 (창 미갱신 상태)
             [{"symbol": "AUSDT", "fundingIntervalHours": 4}])
    dm._refresh_funding_window()
    dm._get_funding("AUSDT"); dm._get_funding("AUSDT")
    assert dm._fr_svc.calls == ["AUSDT", "AUSDT"]


def test_settlement_not_yet_published_retries_until_new_value(monkeypatch):
    last = _now_hour()
    # 정산 직후: premiumIndex는 다음 정산으로 넘어갔으나 fundingRate는 아직 이전 정산 값
    dm = _dm(monkeypatch, {"AUSDT": (0.0001, last - 4 * _H)},
             [{"symbol": "AUSDT", "nextFundingTime": last + 4 * _H}],
             [{"symbol": "AUSDT", "fundingIntervalHours": 4}])
    dm._refresh_funding_window()
    assert dm._get_funding("AUSDT").funding_time == last - 4 * _H
    assert dm._get_funding("AUSDT").funding_time == last - 4 * _H
    assert len(dm._fr_svc.calls) == 2               # 미게시 동안 매번 재조회
    dm._fr_svc.settled["AUSDT"] = (-0.0002, last)   # 새 정산 값 게시
    assert dm._get_funding("AUSDT").funding_rate == -0.0002
    assert dm._get_funding("AUSDT").funding_rate == -0.0002
    assert len(dm._fr_svc.calls) == 3               # 게시 후 저장 값 재사용


def test_unknown_interval_fetches_every_time(monkeypatch):
    last = _now_hour() - 8 * _H + _H                 # 8h 종목 (fundingInfo 없음 → 1h로 간주)
    dm = _dm(monkeypatch, {"AUSDT": (0.0001, last)},
             [{"symbol": "AUSDT", "nextFundingTime": last + 8 * _H}], [])
    dm._refresh_funding_window()
    dm._get_funding("AUSDT"); dm._get_funding("AUSDT")
    assert dm._fr_svc.calls == ["AUSDT", "AUSDT"]   # 최신 확인 불가 → 기존 동작


def test_premium_index_failure_fetches_every_time(monkeypatch):
    last = _now_hour()
    dm = _dm(monkeypatch, {"AUSDT": (0.0001, last)}, [], [{"symbol": "AUSDT", "fundingIntervalHours": 4}])
    dm._refresh_funding_window()
    assert dm._fr_window == {}
    assert dm._client.calls == ["premiumIndex"]     # 실패 시 fundingInfo 생략
    dm._get_funding("AUSDT"); dm._get_funding("AUSDT")
    assert dm._fr_svc.calls == ["AUSDT", "AUSDT"]


def test_fetch_failure_keeps_previous_behaviour(monkeypatch):
    dm = _dm(monkeypatch, {}, [], [])
    assert dm._get_funding("AUSDT") is None
    assert "AUSDT" not in dm._fr_cache


class _LS:
    def fetch(self, sym):
        return LongShortData(sym, 60.0, 40.0, 1.5, 0)


class _OI:
    def fetch_change_pct(self, sym):
        return 0.0


def test_stage2_uses_saved_value_between_settlements(monkeypatch):
    last = _now_hour()
    syms = ["AUSDT", "BUSDT", "CUSDT"]
    dm = _dm(monkeypatch, {s: (0.0001 * (i + 1), last) for i, s in enumerate(syms)},
             [{"symbol": s, "nextFundingTime": last + 8 * _H} for s in syms],
             [{"symbol": s, "fundingIntervalHours": 8} for s in syms])
    dm._ls_svc, dm._oi_svc = _LS(), _OI()
    dm._sorted_tickers = [SymbolTicker(s, 100.0, 1.0, 1.0, 1e9 - i, 101.0, 99.0) for i, s in enumerate(syms)]
    dm._refresh_topn_scores(3)
    dm._refresh_topn_scores(3)
    assert sorted(dm._fr_svc.calls) == sorted(syms)                       # 종목당 1회만 조회
    assert dm._client.calls == ["premiumIndex", "fundingInfo"] * 2      # 정산 시각은 주기마다 갱신
    for i, s in enumerate(syms):
        assert dm._ind_cache[s]["funding_rate"] == 0.0001 * (i + 1) * 100.0   # 기존과 같은 % 변환
