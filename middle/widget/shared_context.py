"""
middle/widget/shared_context.py
공유 컨텍스트 — DataManager 싱글톤 + 헬퍼 함수 단일 정의

순환 import 없이 panel_col1/col2/col3/middle_panel 모두에서 import 가능.
middle_panel.py __init__에서 _data_mgr, _bl_mgr 설정.
"""
from __future__ import annotations

import datetime

# ── DataManager / BlacklistManager 싱글톤 참조 ───────────────
_data_mgr = None
_bl_mgr   = None

# ── 실데이터 전용 헬퍼 함수 ──────────────────────────────────

def is_blacklisted(symbol: str) -> bool:
    """블랙리스트 등록 여부 — 하단 엔진 진입 차단용. 매니저 없으면 False."""
    if _bl_mgr is not None:
        return _bl_mgr.is_blacklisted(symbol)
    return False


MAX_SPREAD_PCT = 0.2   # 배정 차단 기준 — 최근 10분 호가 스프레드 중앙값(%) (2026-10-26 실측 상위100 최대 0.0945%)


def get_wide_spread(symbol: str) -> float | None:
    """호가 스프레드 중앙값(%)이 MAX_SPREAD_PCT 초과면 그 값, 아니면 None (표본·매니저 없음 포함)."""
    if _data_mgr is None:
        return None
    med = _data_mgr.get_spread_median(symbol)
    return med if med is not None and med > MAX_SPREAD_PCT else None


def get_ind(symbol: str) -> dict:
    """실데이터 DataManager에서 지표 반환. DataManager 없으면 빈 dict."""
    if _data_mgr is not None:
        return _data_mgr.get_ind(symbol)
    return {}


def request_detail(symbol: str) -> None:
    """선택 심볼 상세 데이터 즉시 갱신 요청 — 하단 엔진 폴링용."""
    if _data_mgr is not None:
        _data_mgr.request_selected(symbol)


def pin_engine_symbol(symbol: str) -> None:
    """거래 엔진 종목 고정("" = 해제) — WS 봉 마감 수신이 중단 모듈 클릭으로 바뀌지 않게 함."""
    if _data_mgr is not None:
        _data_mgr.set_engine_symbol(symbol)


def get_last_close(symbol: str, tf: str) -> int:
    """캐시된 마지막 마감 봉 close_time(ms) — 엔진 봉 마감 반영 확인용. 없으면 0."""
    if _data_mgr is not None:
        return _data_mgr.get_last_close(symbol, tf)
    return 0


def refresh_detail_now(symbol: str) -> None:
    """쿨다운 없이 즉시 상세 갱신 — 엔진 봉 마감 대기 중 WS 미도착 보완용."""
    if _data_mgr is not None:
        _data_mgr.refresh_detail_now(symbol)


def generate_ohlcv(symbol: str, n: int = 60, interval: str = "5m") -> list:
    """실데이터 DataManager에서 OHLCV 반환. interval 미지정 시 5m 기본값."""
    if _data_mgr is not None:
        return _data_mgr.get_ohlcv(symbol, interval, n)
    return []


def _live_ranking() -> list:
    """실데이터 DataManager에서 랭킹 반환. DataManager 없으면 빈 리스트."""
    return _data_mgr.get_ranking_rows() if _data_mgr is not None else []


def get_ticker_info(sym: str) -> tuple[float, int] | None:
    """심볼의 (24h 변동률%, 거래량 순위) 반환. DataManager 없거나 심볼 없으면 None."""
    if _data_mgr is None:
        return None
    tkr = _data_mgr._tkr_map.get(sym)
    if tkr is None:
        return None
    rank = _data_mgr._vol_rank.get(sym, 999)
    return tkr.price_change_pct, rank


def get_current_sessions() -> list:
    """현재 KST 시각 기준 활성 글로벌 세션 목록 반환."""
    kst_h = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    ).hour
    sessions: list[str] = []
    if 9 <= kst_h < 18:             sessions.append("ASIA")
    if kst_h >= 17 or kst_h < 2:   sessions.append("EU")
    if kst_h >= 22 or kst_h < 7:   sessions.append("US")
    return sessions
