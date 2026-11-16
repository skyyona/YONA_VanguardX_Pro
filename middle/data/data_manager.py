"""
middle/data/data_manager.py
중단 모듈 실데이터 코디네이터 (DataManager)

역할:
  · 전체 ticker 주기적 갱신 (30초마다, 백그라운드 스레드)
  · 선택된 심볼 상세 데이터 온디맨드 갱신
  · get_ind(symbol) → SYMBOL_IND 포맷 dict  (middle_panel.py 하위 호환)
  · get_ranking_rows() → 실데이터 랭킹 행 목록 (11-tuple 리스트)
  · get_ohlcv(symbol, interval, n) → generate_ohlcv() 호환 dict 리스트
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── 배경 갱신 주기 상수 ────────────────────────────────────────
_TICKER_INTERVAL_SEC = 5   # ticker 갱신 (초) — 5초마다 전체 변동률 갱신
_STAGE2_INTERVAL = 60    # 경량 갱신: L/S·FR·OI (초) — Rate Limit 예산 확보 (15→60)
# STAGE2 대상 심볼 수는 100 고정.
# 축소 시 대상 밖 심볼은 갱신이 늦어지는 게 아니라 아예 되지 않으며,
# long_ratio(50.0)/funding_rate(0.0)/oi_change(0.0) 기본값으로 영구 채점된다.
# 이 3개 필드는 sharp_rise·sharp_decline·fourtf·newlisted·player 5개 스코어러가 모두 사용한다.
_STAGE2_TOPN     = 100
_G2_RSI_BARS     = 14 + 5   # M4 준비 G2: 15m 마감 봉 19개 RSI(14) — trading_engine·backtest_runner G2와 동일
_STAGE3_INTERVAL = 60    # klines 갱신: 4TF OHLCV+지표 (초)
# STAGE3 봉 마감 맞춤·새 봉만 받기 (2026-11-16) — 바이낸스 IP 사용량 1분 약 1,200 → 마감된 시간 단위만·새 봉만
_STAGE3_DELAY_MS    = 8_000    # 매분 0초 + 8초 실행 (마감 봉 조회 가능 실측 약 7초)
_STAGE3_RETRY_UNTIL = 50_000   # 새 봉 미게시 시 같은 분 안 재시도 한도 (분 시작 후 50초)
_KLINES_INCR_LIMIT  = 3        # 새 봉만 받을 때 요청 봉 수 (마감 2개 + 진행 1개, 가중치 1)
_TF_MS: dict[str, int] = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
                          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_LOOP_BASE       = 5     # 루프 기본 단위 (초) — TICKER_INTERVAL과 동기화
_SPREAD_INTERVAL = 60    # 호가 스프레드 표본 주기 (초) — bookTicker 전체 1회 가중치 5
_SPREAD_SAMPLES  = 10    # 심볼별 보관 표본 수 → 최근 10분 중앙값 (배정 단계 스프레드 필터)
_STAGE2_WORKERS  = 5     # 경량 갱신 병렬 스레드 수 (3→5: 15초 주기 여유 확보)
_STAGE3_WORKERS  = 7     # klines 갱신 병렬 스레드 수 (3→7: 34초→15초)
# STAGE3에서 갱신할 TF (단기 1m·3m·5m·15m + 일일 1h·4h·1d — middle.analysis.trend 추세 판정)
_KLINES_TFS      = ("1m", "3m", "5m", "15m", "1h", "4h", "1d")
# klines 요청 봉 수 — STAGE3·_refresh_detail·get_ohlcv 세 경로 공통 (미완성 봉 제외 → 마감 봉 = 요청 − 1).
# 경로마다 다르면 같은 TF 캐시를 번갈아 덮어써 지표가 갱신마다 달라진다 (기존 15m 59/79봉).
# 단기 1m·3m·5m·15m 200 → 199봉: StochRSI(G1·G_K·KD 익절·G6)가 백테스트(전체 기록)와 일치 —
#   stochrsi_window_check.py: 15m 59봉 교차 0.73%·79봉 0.15% → 199봉 0.02% 불일치 (5m 59봉 Zone 7.11% → ≈0).
# 1h 200 → 199봉: EMA50(G_ema)·ATR%(G4·G8 청산 근접)·StochRSI(G7.5)가 백테스트와 일치 —
#   59봉 대비 G_ema 불일치 5.30% → 0.00%, ATR% 최대 7.21% → 0.06%, G7.5 기여 1.07% → 0.03% (79봉이면 G_ema 2.43% 잔존).
# 4h·1d 80 → 79봉: G7.5 기여 1.8% → 0.3% (2026-11-01 실측, 59봉 대비).
# 요청 가중치 limit<100 = 1, 100~499 = 2 → 종목당 12 (상위 100 STAGE3 1회 1,200).
_KLINES_LIMITS: dict[str, int] = {
    "1m": 200, "3m": 200, "5m": 200, "15m": 200, "1h": 200,
    "4h": 80,  "1d": 80,
}
# VWAP·5m ATR%는 5m 봉 전체를 쓰므로 5m 199봉 확대 전 창 유지 (VWAP 표시·5m ATR% 손절 제안 값 불변)
_VWAP_ATR5M_BARS_TOPN   = 59   # STAGE3
_VWAP_ATR5M_BARS_DETAIL = 79   # _refresh_detail
# 가격 예고 — 별도 조회 (위 _KLINES_LIMITS 5m 200은 엔진 지표·백테스트 일치 값이라 변경하지 않음)
_FORECAST_CYCLE_MS   = 900_000     # 15분 봉 마감마다
_FORECAST_DELAY_MS   = 240_000     # 마감 후 240초 — 해당 시각 OI(limit 290 조회) 게시: 90초 63~74%·180초 72~82%·240초 100% (2026-11-11 실측 3회, 24h 상위 100)
_FORECAST_TOPN       = 100         # 1열 24h Ticker 목록 (24h 변동률 상위 100)
_FORECAST_WORKERS    = 3
_FORECAST_BARS_LIMIT = 300         # 마감 299봉 ≥ 지표 필요 289 (가중치 2)
_FORECAST_OI_LIMIT   = 290         # 24h OI (futures/data, 가중치 0·IP 1,000회/5분 — 15분 1회 종목당 1회)
_OHLCV_RETRY_SEC     = 30          # get_ohlcv 빈 결과 뒤 재조회 대기 (초)
_FORECAST_KEEP_MS    = 1_800_000   # 조회 실패·일시 부족 시 직전 정상 판정 유지 한도 (30분 — 15분 주기 1회 실패 허용)
# ── 단계별 필드 소유권 ────────────────────────────────────────
# 각 갱신 단계는 자기가 담당하는 필드만 캐시에 병합한다.
# 통째 교체 방식은 네트워크 대기 중 다른 단계가 쓴 결과를 되돌린다.
_STAGE2_FIELDS = ("long_ratio", "funding_rate", "oi_change", "_stage2_ready")
_STAGE3_FIELDS = (
    "atr", "atr_pct", "atr_pct_5m", "vss", "bpr", "price_change_pct",
    "pattern", "align", "e5", "e10", "e20", "e50",
    "volume_ratio", "swing_bull", "swing_bear", "vwap", "_data_ready",
    "tf1", "tf3", "tf5", "tf15", "tf1h", "tf4h", "tf1d",
)

from core import rate_gate
from middle.api.binance_client import MiddleBinanceClient
from middle.data.ticker_data import TickerData
from middle.data.websocket_ticker import WebSocketTicker
from middle.data.websocket_klines import WebSocketKlines
from middle.data.ohlcv_data import OHLCVData
from middle.data.funding_rate_data import FundingRateFetcher
from middle.data.open_interest_data import OpenInterestFetcher
from middle.data.longshort_data import LongShortFetcher
from middle.models import OHLCVBar, SymbolTicker, FundingRateData
from middle.analysis.forecast import compute_features, Forecaster, INSUFFICIENT_TEXT, log_path as forecast_log_path
# M4 준비(1열) = 엔진 M4Entry와 같은 G2 RSI 함수·같은 모드 설정(use_macro) — 엔진 모듈은 중단을 import하지 않음(순환 없음)
from bottom_engine.strategy.rsi_divergence import calc_rsi_series
from bottom_engine.strategy_settings.strategy_loader import StrategyLoader

from middle.col3_analysis_panels.technical_analysis.rsi import RSI
from middle.col3_analysis_panels.technical_analysis.bpr import BPR
from middle.col3_analysis_panels.technical_analysis.vss import VSS
from middle.analysis.atr_percent import AtrPercent
from middle.col3_analysis_panels.technical_analysis.ema_alignment import EMAAlignment
from middle.col3_analysis_panels.technical_analysis.vwap import VWAP
from middle.col3_analysis_panels.technical_analysis.candle_pattern import CandlePattern
from middle.col2_chart_indicators.mtf_stochrsi import StochRSI, StochRSIResult
from middle.col2_chart_indicators.divergence_detector import DivergenceDetector
from middle.col3_analysis_panels.derivative_analysis.liquidation_proximity import LiquidationProximityPanel
from middle.col3_analysis_panels.comprehensive_analysis.recommended_leverage import RecommendedLeverage
from middle.analysis.tag_detector import TagDetector, TagDetectionResult
from middle.col3_analysis_panels.player_detection.energy_balance import EnergyBalance

# ── 색상 상수 (middle_panel.py 와 동일 팔레트) ─────────────────
_POS  = "#11de93"
_NEG  = "#ff007a"
_ORA  = "#FF8C25"
_YEL  = "#FFD700"
_DIM  = "#555555"
_BLU  = "#4EA1FF"
_LGR  = "#8ad7b5"

# StochRSI detail TFs
_DETAIL_TFS = ("1m", "3m", "5m", "15m", "1h", "4h", "1d")

# 선택 심볼 갱신 쿨다운 (초)
_DETAIL_COOLDOWN = 3   # 동일 심볼 재클릭 쿨다운 10초→3초 (반응성 개선)


def _dir_col(direction: str) -> str:
    if direction == "▲": return _POS
    if direction == "▼": return _NEG
    return _YEL


def _fmt_elapsed(seconds: float) -> str:
    """교차 후 경과 시간 포맷."""
    if seconds < 60:   return "방금"
    if seconds < 3600: return f"{int(seconds // 60)}분 전"
    return f"{int(seconds // 3600)}시간 전"


def _days_since_listing(onboard_date_ms: int) -> int:
    """상장 후 경과일 (소수점 버림) — onboard_date_ms: exchangeInfo symbols[i].onboardDate (Unix ms).
    엔진 신규 상장 금지(G8 common_new) 판정 입력(_days_listed)이자 Newly Listed·신규 배지 기준."""
    diff_ms = int(time.time() * 1000) - onboard_date_ms
    return max(0, diff_ms // (24 * 60 * 60 * 1000))


def _build_onboard_map(exchange_info: dict) -> dict[str, int]:
    """exchangeInfo 응답에서 symbol → onboardDate(ms) 매핑 생성."""
    result: dict[str, int] = {}
    for sym_info in exchange_info.get("symbols", []):
        symbol = sym_info.get("symbol", "")
        onboard = sym_info.get("onboardDate")
        if symbol and onboard:
            result[symbol] = int(onboard)
    return result


def _has_newer(cur: dict, bars: dict) -> bool:
    """캐시(cur)에 bars보다 최신 마감 봉이 있는 TF가 하나라도 있으면 True — 늦게 도착한 오래된 봉의 덮어쓰기 방지."""
    for tf, cb in cur.items():
        nb = bars.get(tf)
        if cb and (not nb or cb[-1].close_time > nb[-1].close_time):
            return True
    return False


def _latest_close_ms(tf: str, now_ms: int) -> int:
    """now_ms 기준 마지막 마감 봉의 마감 시각(+1ms = 진행 중 봉 open_time). 바이낸스 봉 경계 = UTC epoch 배수."""
    step = _TF_MS[tf]
    return now_ms // step * step


def _splice_bars(cur: list, new: list, need: int) -> list | None:
    """저장 마감 봉 cur 뒤에 new의 새 마감 봉을 이어붙여 최근 need개 유지 (전체 조회와 같은 목록).
    새 봉 없음 → cur 그대로. 이어지지 않음(빠진 봉) → None (호출부가 전체 조회)."""
    last = cur[-1].close_time
    fresh = [b for b in new if b.close_time > last]
    if not fresh:
        return cur
    prev = last
    for b in fresh:
        if b.open_time != prev + 1:
            return None
        prev = b.close_time
    return (cur + fresh)[-need:]


def _apply_liq(ind: dict) -> None:
    """갱신 대상 행 청산 근접도 — 상세 경로(_compute_detail)와 같은 함수·입력(1h ATR%·FR%·롱 비율).
    STAGE2(FR·롱 비율)와 STAGE3(1h ATR%)가 모두 반영된 뒤에만 계산 — 그 전에는 기본값(±2.0) 유지."""
    if ind.get("_data_ready") and ind.get("_stage2_ready"):
        liq = LiquidationProximityPanel.estimate(ind["atr_pct"], ind["funding_rate"], ind["long_ratio"])
        ind["liq_long_pct"]  = liq.liq_long_pct
        ind["liq_short_pct"] = liq.liq_short_pct


def _read_logged_times(path: Path, tail_bytes: int = 262_144) -> dict[str, int]:
    """가격 예고 기록 파일 끝부분(약 256KB ≈ 최근 2,500행 · 15분 100행 기준 약 6시간)의 종목별 마지막 판정 시각.
    파일 없음·읽기 실패 → 빈 dict. 형식이 다른 줄(헤더·잘린 첫 줄)은 건너뛴다."""
    out: dict[str, int] = {}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return out
    if size > tail_bytes and lines:
        lines = lines[1:]                    # 중간부터 읽은 첫 줄은 잘렸을 수 있음
    for line in lines:
        parts = line.split(",", 2)
        if len(parts) < 3:
            continue
        try:
            t = int(parts[0])
        except ValueError:
            continue
        if t > out.get(parts[1], 0):
            out[parts[1]] = t
    return out


def _stoch_tf_dict(r: StochRSIResult | None) -> dict:
    """StochRSIResult → tf dict (SYMBOL_IND 포맷)."""
    if r is None:
        return {"dir": "↔", "col": _YEL, "k": 50.0, "d": 50.0,
                "elapsed": None, "div": None,
                "k_series": [], "d_series": [], "recent_volumes": []}
    # elapsed: 크로스 여부로 단순 추정
    elapsed = "방금" if r.direction != "↔" else None
    return {"dir": r.direction, "col": _dir_col(r.direction),
            "k": r.k, "d": r.d, "elapsed": elapsed, "div": None,
            "k_series": [], "d_series": []}


class MiddleDataManager:
    """중단 모듈 전체 데이터 파이프라인 코디네이터."""

    def __init__(self) -> None:
        self._client    = MiddleBinanceClient()
        self._tkr_svc   = TickerData(self._client)
        self._ohlcv_svc = OHLCVData(self._client)
        self._fr_svc    = FundingRateFetcher(self._client)
        self._oi_svc    = OpenInterestFetcher(self._client)
        self._ls_svc    = LongShortFetcher(self._client)

        # ── 캐시 ───────────────────────────────────────────────
        self._tickers:         list[SymbolTicker]         = []   # API 응답 원본 순서
        self._sorted_tickers:  list[SymbolTicker]         = []   # 거래량 내림차순 정렬
        self._tkr_map:         dict[str, SymbolTicker]    = {}
        self._vol_rank:        dict[str, int]             = {}
        self._ind_cache:       dict[str, dict]            = {}   # symbol → ind dict
        self._ohlcv_cache:     dict[str, dict[str, list[OHLCVBar]]] = {}
        self._ranking_rows:    list                       = []
        self._sort_mode:       str                        = "24h Ticker"   # 1열 Sort by — M4 준비 G7.5 적용 여부 기준
        self._onboard_map:     dict[str, int]             = {}
        self._cross_ts_cache:  dict[str, dict[str, float]] = {}  # sym→{tf_key→교차 unix ts}
        self._spread_hist:     dict[str, deque]           = {}   # symbol → 최근 스프레드(%) 표본
        self._deriv_cache:     dict[str, tuple]           = {}   # symbol → (fr, oi, ls) 마지막 REST 값 — WS 봉 마감 재계산용
        # 정산 펀딩비 재사용 — 값은 정산 시각에만 바뀌므로 다음 정산 전 재조회 생략 (fundingRate 500회/5분/IP 한도)
        self._fr_cache:        dict[str, FundingRateData] = {}   # symbol → 마지막으로 받은 정산 펀딩비
        self._fr_window:       dict[str, tuple[int, int]] = {}   # symbol → (마지막 정산 시각, 다음 정산 시각) ms
        # 가격 예고 — 판정식 forecast_params.json (없거나 형식 오류면 비활성)
        self._forecaster = Forecaster.load()
        self._forecast_log: Path = forecast_log_path(self._forecaster.version)   # 판정식 버전별 기록 파일
        self._forecast_checked: dict[str, int] = {}                             # symbol → 마지막 계산 5분 구간
        # 1열 목록 제외 판정(블랙리스트) — middle_panel이 BlacklistManager.is_blacklisted 연결. 24h 목록·예고 목록 공용
        self._list_excluded = lambda symbol: False
        # 주기 작업 겹침 방지·시작 직후 요청 몰림 분산 (2026-11-15)
        self._jobs_running: set[str] = set()      # 실행 중 주기 작업 이름 (STAGE2·STAGE3·예고)
        self._stage3_done = False                  # 시작 후 STAGE3 첫 갱신 완료 — 그 전엔 예고 판정 안 함
        self._stage3_minute = -1                   # 마지막 STAGE3 실행 분 (분 0초 + _STAGE3_DELAY_MS 기준)
        self._stage3_stale = False                 # 마지막 STAGE3에서 새 마감 봉 미게시 TF 있음 → 같은 분 안 재시도
        self._ohlcv_fail: dict[tuple[str, str], float] = {}   # (symbol, tf) → get_ohlcv 빈 결과 시각
        self._forecast:        dict[str, dict]            = {}   # symbol → get_forecast() 기록
        self._forecast_slot:   int                        = -1   # 마지막 실행 15분 구간 (-1 = 시작 첫 확인)
        self._forecast_logged: dict[str, int] | None      = None # symbol → 마지막 기록 판정 시각 (None = 파일에서 아직 안 읽음)

        # ── 상태 ───────────────────────────────────────────────
        self._last_tkr_refresh: float = 0.0
        # REST 전체 시세 1회 이상 성공 여부 — 성공 전엔 WS 수신 중에도 REST 재시도 (WS는 바뀐 종목만 보내므로
        # 시작 시 REST 실패 후 WS만으로는 일부 종목 목록이 됨 — 2026-11-16)
        self._tickers_full_loaded: bool = False
        # Fix②: 실데이터 준비 완료 시 화면 재갱신 콜백 (middle_panel이 등록)
        self._on_detail_ready_cb:  "callable | None" = None   # 심볼 상세 갱신 콜백
        self._on_ranking_ready_cb: "callable | None" = None   # ticker 갱신 완료 콜백
        self._on_klines_ready_cb:  "callable | None" = None   # STAGE3 완료 콜백 → TF합의 즉시 반영
        self._last_detail_sym:  str   = ""
        self._last_detail_time: float = 0.0
        self._engine_sym:       str   = ""   # 거래 엔진 종목 — 설정 중에는 WS klines가 이 종목에 고정
        self._lock = threading.Lock()
        # WebSocket 실시간 ticker (1초 Push)
        self._ws_ticker: WebSocketTicker | None = None
        # WebSocket klines — 선택 심볼 봉 마감 즉시 감지
        self._ws_klines: WebSocketKlines | None = None
        self._ws_update_count: int = 0   # rebuild_ranking_rows 주기 카운터
        self._running: bool = False      # auto_refresh_loop 실행 여부
        self._last_refresh_error:      str   = ""
        self._last_refresh_error_time: float = 0.0

    # ══ 공개 인터페이스 ══════════════════════════════════════════

    def start_auto_refresh(self) -> None:
        """백그라운드 자동 갱신 시작."""
        if self._running:
            return   # 이미 실행 중이면 무시
        self._running = True
        self._ws_ticker = WebSocketTicker(on_update=self._on_ws_ticker_update)
        self._ws_ticker.start()
        self._ws_klines = WebSocketKlines(on_closed=self._on_kline_closed)
        self._ws_klines.start(self._engine_sym or self._last_detail_sym)
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()

    def stop_auto_refresh(self) -> None:
        """백그라운드 자동 갱신 중지 + 캐시 초기화."""
        self._running = False
        if self._ws_ticker is not None:
            try:
                self._ws_ticker.stop()
            except Exception:
                pass
            self._ws_ticker = None
        if self._ws_klines is not None:
            try:
                self._ws_klines.stop()
            except Exception:
                pass
            self._ws_klines = None
        # 캐시 초기화 — STOP 후 재START 시 신선한 데이터
        with self._lock:
            self._tickers.clear()
            self._sorted_tickers.clear()
            self._tkr_map.clear()
            self._ind_cache.clear()
            self._ohlcv_cache.clear()
            self._ranking_rows.clear()
            self._cross_ts_cache.clear()
            self._spread_hist.clear()
            self._deriv_cache.clear()
            self._forecast.clear()
            self._forecast_checked.clear()
            self._forecast_slot = -1
            self._stage3_done = False
            self._stage3_minute = -1
            self._stage3_stale = False
            self._tickers_full_loaded = False

    def request_selected(self, symbol: str) -> None:
        """선택 심볼 상세 데이터 비동기 갱신 요청."""
        now = time.time()
        with self._lock:
            if (symbol == self._last_detail_sym
                    and now - self._last_detail_time < _DETAIL_COOLDOWN):
                return
            self._last_detail_sym  = symbol
            self._last_detail_time = now
            pinned = bool(self._engine_sym)
        if self._ws_klines is not None and not pinned:
            self._ws_klines.set_symbol(symbol)
        threading.Thread(target=self._refresh_detail, args=(symbol,), daemon=True).start()
        if self._running and self._forecaster.ok:   # 가격 예고 — 자동 갱신 중에만 (최근 5m 마감 기준 재계산)
            threading.Thread(target=self._refresh_selected_forecast, args=(symbol,), daemon=True).start()

    def set_engine_symbol(self, symbol: str) -> None:
        """거래 엔진 종목 고정("" = 해제). 고정 중에는 WS klines가 이 종목만 구독 — 중단 모듈 클릭으로 바뀌지 않음."""
        with self._lock:
            self._engine_sym = symbol
            ws_sym = symbol or self._last_detail_sym
        if self._ws_klines is not None and ws_sym:
            self._ws_klines.set_symbol(ws_sym)
        if symbol:
            threading.Thread(target=self._refresh_detail, args=(symbol,), daemon=True).start()

    def refresh_detail_now(self, symbol: str) -> None:
        """쿨다운 없이 즉시 상세 갱신(백그라운드) — 엔진 봉 마감 대기 중 WS 미도착 보완용."""
        threading.Thread(target=self._refresh_detail, args=(symbol,), daemon=True).start()

    def get_last_close(self, symbol: str, tf: str) -> int:
        """캐시된 마지막 마감 봉 close_time(ms). 봉이 없으면 0."""
        with self._lock:
            bars = self._ohlcv_cache.get(symbol, {}).get(tf)
            return bars[-1].close_time if bars else 0

    def get_ind(self, symbol: str) -> dict:
        """SYMBOL_IND 포맷 dict 반환 (캐시 우선, 없으면 ticker 기반 기본값)."""
        cached = self._ind_cache.get(symbol)
        if cached:
            ob = self._onboard_map.get(symbol, 0)
            cached["_days_listed"] = (
                _days_since_listing(ob) if ob else 9999
            )
            return cached
        tkr = self._tkr_map.get(symbol)
        if tkr:
            return self._simple_ind(tkr)
        return self._default_ind()

    def get_ranking_rows(self) -> list:
        """실데이터 랭킹 행 목록 반환 (11-tuple 리스트)."""
        if self._ranking_rows:
            return self._ranking_rows
        # 캐시 없으면 ticker 기반 즉시 생성
        use_macro = self._m4_use_macro()
        return [self._make_row(t, use_macro) for t in self._tickers[:200]]

    def set_sort_mode(self, mode: str) -> None:
        """1열 Sort by 변경 — M4 준비 G7.5 적용 기준(같은 이름 엔진 모드의 use_macro) 교체 후 랭킹 풀 즉시 재생성.
        표시 전용: 하단 엔진 모드·설정은 바꾸지 않는다 (읽기만)."""
        with self._lock:
            self._sort_mode = mode
        self._rebuild_ranking_rows()

    def _m4_use_macro(self) -> bool:
        """1열 Sort by와 이름이 같은 엔진 모드의 use_macro (_strategy.json, 없으면 엔진 기본값) — 행 생성 1회마다 읽음."""
        with self._lock:
            mode = self._sort_mode
        return StrategyLoader.load_or_default(mode).use_macro

    def get_ohlcv(self, symbol: str, interval: str = "5m", n: int = 60) -> list[dict]:
        """generate_ohlcv() 호환 dict 리스트 반환.
        캐시 없으면 갱신 경로와 같은 봉 수(_KLINES_LIMITS)로 받아 캐시 — 짧은 목록이 캐시에 남지 않게 함."""
        bars = self._ohlcv_cache.get(symbol, {}).get(interval, [])
        key = (symbol, interval)
        # 빈 결과(조회 실패·차단) 뒤 _OHLCV_RETRY_SEC 안에는 다시 조회하지 않음 — 하단 차트 약 2초 갱신이 매번
        # 재조회하던 문제 (2026-11-15)
        if not bars and time.time() - self._ohlcv_fail.get(key, 0.0) >= _OHLCV_RETRY_SEC:
            try:
                bars = self._ohlcv_svc.fetch(symbol, interval, _KLINES_LIMITS[interval])
                sym_cache = self._ohlcv_cache.setdefault(symbol, {})
                sym_cache[interval] = bars
            except Exception:
                bars = []
            if bars:
                self._ohlcv_fail.pop(key, None)
            else:
                self._ohlcv_fail[key] = time.time()
        return [{"o": b.open, "h": b.high, "l": b.low,
                 "c": b.close, "v": b.quote_volume} for b in bars[-n:]]

    def get_listing_days(self, symbol: str) -> int:
        """상장 경과일 — 랭킹 행 [1]·신규 배지·Newly Listed 기준과 같은 정의 (onboardDate 미상 → 0)."""
        ob = self._onboard_map.get(symbol, 0)
        return _days_since_listing(ob) if ob else 0

    def get_ticker(self, symbol: str) -> SymbolTicker | None:
        """심볼 최신 24h ticker (WS·REST 병합본). 없으면 None."""
        return self._tkr_map.get(symbol)

    def get_spread_median(self, symbol: str) -> float | None:
        """최근 표본(최대 _SPREAD_SAMPLES개) 호가 스프레드 중앙값(%). 표본 없으면 None."""
        with self._lock:
            hist = self._spread_hist.get(symbol)
            return statistics.median(hist) if hist else None

    def _ind_fresh(self, symbol: str) -> bool:
        """지표 캐시가 지금 갱신되는 종목인지 — 거래량 상위 100(STAGE2·3 대상)·엔진 종목·선택 종목.
        그 밖(갱신 대상에서 빠진 종목)에 남은 캐시는 옛 값이라 1열 행·Player 표시에 쓰지 않는다
        (2026-11-12 — 급등 때 100위 안에 들었다 빠진 종목이 옛 '롱 대기'·추세 단계를 계속 표시하던 문제).
        엔진 입력(get_ind)은 바꾸지 않는다."""
        return (self._vol_rank.get(symbol, 999) <= _STAGE2_TOPN
                or symbol in (self._engine_sym, self._last_detail_sym))

    def get_row(self, symbol: str) -> tuple | None:
        """종목 하나의 1열 행(11-tuple) — 1열 목록과 같은 _make_row·현재 Sort by의 use_macro. 시세 없으면 None.
        3열이 거래량 상위 200(get_ranking_rows) 밖 종목(24h Ticker·Newly Listed 목록)도 1열과 같은 값을 쓰도록."""
        tkr = self._tkr_map.get(symbol)
        return self._make_row(tkr, self._m4_use_macro()) if tkr is not None else None

    def get_player(self, symbol: str) -> TagDetectionResult | None:
        """Player Detection 단일 정의 — 캐시 지표(STAGE2·STAGE3·상세 갱신) 7개 입력.
        has_rise_tag·has_decline_tag는 절단 전 전체 태그 기준, tags는 강도순 상위 4개(표시용).
        1열 행 배경·Sharp rise/decline Player 가산점·Gold·3열 Player 가산점이 함께 사용.
        지표 없음·갱신 대상 밖(_ind_fresh 아님) → None.
        (엔진 금지 조건용 ind["_player_keys"]와는 별개 — 상세 갱신 시점 값)"""
        if not self._ind_fresh(symbol):
            return None
        ind = self.get_ind(symbol)
        if not ind:
            return None
        return TagDetector.detect(
            long_pct      = ind.get("long_ratio",       50.0),
            fr_pct        = ind.get("funding_rate",      0.0),
            oi_change_pct = ind.get("oi_change",         0.0),
            vss           = ind.get("vss",               1.0),
            bpr           = ind.get("bpr",               0.5),
            atr_pct       = ind.get("atr",               2.0),
            price_chg_pct = ind.get("price_change_pct",  0.0),
        )

    def get_player_map(self, symbols: list[str] | None = None) -> dict[str, dict]:
        """Player 감지 — 태그가 감지된 심볼만. symbols: 대상 종목(1열에 표시할 목록), None이면 랭킹 풀(거래량 상위 200).
        {symbol: {"tags": [(tag_text, tag_color, strength_pct), ...] 강도순 상위 4,
                  "direction": "long" | "short" | "mixed",   # 상승 태그만 / 하락 태그만 / 둘 다
                  "has_rise": bool, "has_decline": bool}}"""
        result: dict[str, dict] = {}
        syms = symbols if symbols is not None else [row[0] for row in self.get_ranking_rows()]
        for sym in syms:
            try:
                det = self.get_player(sym)
            except Exception:
                continue
            if det is None or not det.tags:
                continue
            has_rise, has_decline = det.has_rise_tag, det.has_decline_tag
            direction = "mixed" if has_rise and has_decline else ("long" if has_rise else "short")
            result[sym] = {"tags": [(t.tag_text, t.tag_color, t.strength_pct) for t in det.tags],
                           "direction": direction,
                           "has_rise": has_rise, "has_decline": has_decline}
        return result

    def fetch_exchange_info(self) -> dict | None:
        """exchangeInfo 1회 조회 (동기) — 1열 Blacklist 탭 Settling 감지용."""
        return self._client.fetch_exchange_info()

    def fetch_pending_listings(self) -> list[tuple[dict, dict | None]] | None:
        """PENDING_TRADING 상장 예정 USDT 심볼 원본 조회 (동기) — exchangeInfo 1회 + 심볼당 markPrice 1회.
        반환: [(exchangeInfo 심볼 dict, premiumIndex 응답 또는 None), ...] onboardDate 오름차순.
        exchangeInfo 조회 실패·예외 → None (조회 실패를 '상장 예정 없음'과 구분)."""
        result: list[tuple[dict, dict | None]] = []
        try:
            info = self._client.fetch_exchange_info()
            if not info:
                return None
            pending = [
                s for s in info.get("symbols", [])
                if s.get("symbol", "").endswith("USDT")
                and s.get("status") == "PENDING_TRADING"
            ]
            pending.sort(key=lambda s: s.get("onboardDate", 0))
            for s in pending:
                result.append((s, self._client.fetch_mark_price(s["symbol"])))
        except Exception as e:
            logging.warning("middle fetch_pending_listings: %s", e)
            return None
        return result

    def refresh_tickers_now(self) -> None:
        """즉시 ticker 갱신 (동기, 초기화 시 사용)."""
        threading.Thread(target=self._refresh_tickers, daemon=True).start()

    def _resolve_elapsed(
        self, sym: str, tf_key: str, new_dir: str, old_dir: str
    ) -> str | None:
        """StochRSI 교차 시점 기반 실제 elapsed 계산.

        - new_dir == "↔": 교차 없음 → None (캐시에서 제거)
        - new_dir != old_dir: 새 교차 발생 → 현재 시점 기록 후 "방금"
        - new_dir == old_dir: 기존 교차 유지 → 기록된 시점에서 경과 시간 포맷
        """
        if new_dir == "↔":
            with self._lock:
                self._cross_ts_cache.get(sym, {}).pop(tf_key, None)
            return None
        now = time.time()
        with self._lock:
            sym_cache = self._cross_ts_cache.setdefault(sym, {})
            if new_dir != old_dir or tf_key not in sym_cache:
                # 방향 전환 또는 최초 기록 — 교차 시점 저장
                sym_cache[tf_key] = now
                return "방금"
            return _fmt_elapsed(now - sym_cache[tf_key])

    # ══ 내부 갱신 ══════════════════════════════════════════════

    def _auto_refresh_loop(self) -> None:
        """4단계 자동 갱신 루프 (데몬 스레드, 5초 기본 단위).

        Ticker: 5초마다  — 전체 24h 변동률 갱신 → 랭킹 순위 반영
        STAGE2: 60초마다 — L/S·FR·OI 경량 갱신 → Sharp 별점·필터 정확도
        STAGE3: 매분 봉 마감 + 8초 — 7TF klines 갱신(마감된 TF만 새 봉 조회) → TF정렬·ATR%·EMA·4TF별점
        STAGE1: 클릭 즉시 — request_selected() 에서 처리
        """
        # ── 초기 실행 ─────────────────────────────────────────
        self._refresh_tickers()
        self._fetch_onboard_map()
        self._start_job("stage2", self._refresh_topn_scores, _STAGE2_TOPN)
        self._stage3_minute = (int(time.time() * 1000) - _STAGE3_DELAY_MS) // 60_000
        self._start_job("stage3", self._refresh_topn_klines, 100)
        threading.Thread(target=self._refresh_spreads, daemon=True).start()

        # ── 주기 카운터 (5초 단위) ────────────────────────────
        _elapsed = 0   # 누적 경과 시간 (초)

        while self._running:
            time.sleep(_LOOP_BASE)   # 5초 대기 (기본 단위)
            if not self._running:
                break
            _elapsed += _LOOP_BASE

            # ── Ticker: WebSocket 실제 데이터 수신 중일 때만 REST 건너뜀 ──
            # WebSocket 연결(is_connected=True)만으로는 충분하지 않음:
            # 한국 IP에서 연결은 되나 데이터 Push가 없는 상황 존재
            # → 실제 데이터를 받은 경우(has_received_data=True)만 REST 스킵
            #   전체 REST 시세가 한 번도 성공하지 못했으면 WS 수신 중에도 재시도 (_tickers_full_loaded)
            if _elapsed % _TICKER_INTERVAL_SEC == 0 and rate_gate.remaining() <= 0:   # 차단 중 REST 생략
                if (self._ws_ticker is None or not self._ws_ticker.has_received_data
                        or not self._tickers_full_loaded):
                    self._refresh_tickers()

            # ── STAGE2: 60초마다 경량 갱신 (L/S·FR·OI) ───────
            if _elapsed % _STAGE2_INTERVAL == 0:
                self._start_job("stage2", self._refresh_topn_scores, _STAGE2_TOPN)

            # ── STAGE3: 매분 봉 마감 + 8초 klines 갱신 (마감된 TF만 새 봉 조회) ──
            #   새 봉 미게시 TF가 있으면 같은 분 50초까지 5초마다 재시도 (최신 종목은 조회·계산 생략)
            _now_ms = int(time.time() * 1000)
            _minute = (_now_ms - _STAGE3_DELAY_MS) // 60_000
            if _minute != self._stage3_minute:
                self._stage3_minute = _minute
                self._start_job("stage3", self._refresh_topn_klines, 100)
            elif self._stage3_stale and _now_ms % 60_000 < _STAGE3_RETRY_UNTIL:
                self._start_job("stage3", self._refresh_topn_klines, 100)

            if _elapsed % _STAGE3_INTERVAL == 0:
                # WS klines 미수신 시 선택 심볼 지표 고착 방지 (엔진 정지 상태 대응)
                if self._ws_klines is None or not self._ws_klines.has_received_data:
                    with self._lock:
                        _fallback_sym = self._last_detail_sym
                    if _fallback_sym:
                        _ws_err = (self._ws_klines.last_error
                                   if self._ws_klines is not None else "")
                        if _ws_err:
                            with self._lock:
                                self._last_refresh_error      = _ws_err
                                self._last_refresh_error_time = time.time()
                            logging.warning("middle WS: %s", _ws_err)
                        self.request_selected(_fallback_sym)

            # ── 호가 스프레드: 60초마다 전체 표본 1회 ─────────
            if _elapsed % _SPREAD_INTERVAL == 0:
                threading.Thread(target=self._refresh_spreads, daemon=True).start()

            # ── 가격 예고: 15분 봉 마감 + 240초마다 24h 상위 100·선택 종목 ──
            #   시작 후 STAGE3 첫 갱신이 끝난 뒤부터 (시작 1분 요청 몰림 분산 — 11-13 시작 분 1,501·판정 분 1,818)
            if self._stage3_done and self._forecast_due(int(time.time() * 1000)):
                self._start_job("forecast", self._refresh_forecasts)

            # ── 카운터 리셋 (1시간 기준) + onboard_map 갱신 ──
            if _elapsed >= 3600:
                threading.Thread(target=self._fetch_onboard_map, daemon=True).start()
                _elapsed = 0

    # ══ 가격 예고 (화면 표시 전용 — 엔진·백테스트 미사용) ══════════

    def get_forecast(self, symbol: str) -> dict | None:
        """{"t": 판정 봉 마감 ms, "feats", "result", "text", "status", "price"} — 계산 전이면 None,
        연속 기록 부족이면 feats·result·price None + 판단 보류 문구."""
        with self._lock:
            return self._forecast.get(symbol)

    def _forecast_one(self, symbol: str, in_list: bool) -> dict | None:
        """5m 봉 300개(마감 299)·5m OI 290개 조회 → 지표·판정 (forecast.compute_features·Forecaster 단일 정의).
        in_list: 1열 24h Ticker 목록(24h 변동률 상위 100) 종목 — 목록 조건 경계로 판정."""
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._forecast_checked[symbol] = now_ms // 300_000
        bars = self._ohlcv_svc.fetch(symbol, "5m", _FORECAST_BARS_LIMIT)
        oi   = self._oi_svc.fetch_series(symbol, "5m", _FORECAST_OI_LIMIT)
        feats = compute_features(bars, oi)
        if feats is None and bars and (bars[-1].close_time + 1) not in oi:
            bars = bars[:-1]                     # 마지막 봉 마감 OI 미게시(마감 후 최대 약 240초) → 직전 마감 봉 기준
            feats = compute_features(bars, oi)
        if feats is None:   # 판단 보류 표시 (기록 파일 제외)
            with self._lock:
                prev = self._forecast.get(symbol)
                # 조회 일시 실패(빈 응답)·일시 부족: 30분 안의 직전 정상 판정은 유지 — '휴장·신규 상장' 오표시·판정 소실 방지
                if prev is None or prev["feats"] is None or now_ms - prev["t"] > _FORECAST_KEEP_MS:
                    self._forecast[symbol] = {"t": bars[-1].close_time + 1 if bars else 0, "feats": None,
                                              "result": None, "text": INSUFFICIENT_TEXT, "status": "", "price": None}
            return None
        result = self._forecaster.judge(feats, in_list)
        text, status = self._forecaster.display(result)
        rec = {"t": bars[-1].close_time + 1, "feats": feats, "result": result,
               "text": text, "status": status, "price": bars[-1].close}
        with self._lock:
            self._forecast[symbol] = rec
        return rec

    def _refresh_forecasts(self) -> None:
        """판정 → 캐시 갱신·기록 파일 추가(4주 실사용 검증용).
        대상: 24h 변동률 상위 100(1열 24h Ticker 목록, 'list' 조건) + 그 밖 거래량 상위 100('all' 조건 — 검증 표본,
        2026-11-12 추가: 그 밖 조건 표시가 기록 0행이라 검증 불가였음) + 선택 종목."""
        with self._lock:
            by_vol = list(self._sorted_tickers[:_FORECAST_TOPN])
            selected = self._last_detail_sym
        list_syms = [t.symbol for t in self._change_ranked(_FORECAST_TOPN)]
        in_set = set(list_syms)
        other_syms = [t.symbol for t in by_vol if t.symbol not in in_set]
        syms = list_syms + other_syms
        flags = [True] * len(list_syms) + [False] * len(other_syms)
        if selected and selected not in syms:
            syms.append(selected)
            flags.append(False)
        if not syms or not self._forecaster.ok:
            return
        with ThreadPoolExecutor(max_workers=_FORECAST_WORKERS) as pool:
            recs = list(pool.map(self._forecast_one_safe, syms, flags))
        self._append_forecast_log([(s, r) for s, r in zip(syms, recs) if r is not None])
        cb = self._on_detail_ready_cb
        if cb is not None and selected and selected in syms:
            try:
                cb(selected)
            except Exception:
                pass

    def _forecast_one_safe(self, symbol: str, in_list: bool) -> dict | None:
        rate_gate.defer_if_over_soft_cap()   # 이번 분 IP 사용량 1,900 이상 → 다음 분까지 대기 (2026-11-16)
        if rate_gate.remaining() > 0:   # 차단 중 — 조회하지 않음 (직전 판정 유지)
            return None
        try:
            return self._forecast_one(symbol, in_list)
        except Exception as e:
            logging.warning("middle forecast %s: %s", symbol, e)
            return None

    def _forecast_due(self, now_ms: int) -> bool:
        """판정 실행 여부 — 15분 봉 마감 + _FORECAST_DELAY_MS마다 1회.
        시작(앱 실행·STOP 후 START) 첫 확인: 마감 후 대기 시간 안이면 곧 있을 정기 실행을 기다리고
        (같은 봉 두 번 판정 방지 — 2026-11-10 23:01 시작 시 93행 중복), 그 밖이면 바로 실행."""
        slot = (now_ms - _FORECAST_DELAY_MS) // _FORECAST_CYCLE_MS
        if self._forecast_slot == -1:
            self._forecast_slot = slot
            return now_ms % _FORECAST_CYCLE_MS >= _FORECAST_DELAY_MS
        if slot != self._forecast_slot:
            self._forecast_slot = slot
            return True
        return False

    def _append_forecast_log(self, rows: list) -> None:
        """data/forecast_log_{판정식 버전}.csv — 판정 시점·종목·조건·가격·점수·해당 표시(채택 여부 무관 전체 후보) 기록.
        이미 기록한 판정 시점 이하(같은 봉 재판정·직전 봉 대체 판정)는 건너뛴다 — 앱 재시작 후에도
        기존 파일 끝부분에서 종목별 마지막 기록 시점을 읽어 이어간다."""
        if self._forecast_logged is None:
            self._forecast_logged = _read_logged_times(self._forecast_log)
        rows = [(s, r) for s, r in rows if r["t"] > self._forecast_logged.get(s, 0)]
        if not rows:
            return
        new = not self._forecast_log.exists()
        try:
            self._forecast_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self._forecast_log, "a", encoding="utf-8", newline="") as f:
                if new:
                    f.write("t_close,symbol,context,price,r24,score_dn,score_up,score_big,labels,shown\n")
                for sym, r in rows:
                    sc = r["result"].get("scores", {})
                    f.write(f"{r['t']},{sym},{r['result']['context']},{r['price']},{r['feats']['r24']:.4f},"
                            f"{sc.get('dn', 0):.6f},{sc.get('up', 0):.6f},{sc.get('big', 0):.6f},"
                            f"{'|'.join(r['result'].get('labels', []))},{'|'.join(r['result'].get('shown', []))}\n")
                    self._forecast_logged[sym] = r["t"]
        except OSError as e:
            logging.warning("middle forecast log: %s", e)

    def _refresh_selected_forecast(self, symbol: str) -> None:
        """선택 종목 예고 — 마지막 판정이 최근 마감 5m 봉보다 이전이면 재계산 후 화면 갱신 콜백.
        같은 5분 구간에 이미 계산했으면 생략 (판단 보류 종목을 30초마다 다시 조회하던 문제 — 2026-11-12)."""
        cur = self.get_forecast(symbol)
        now_ms = int(time.time() * 1000)
        last_close = (now_ms - 60_000) // 300_000 * 300_000
        if cur is not None and cur["t"] >= last_close:
            return
        with self._lock:
            if self._forecast_checked.get(symbol) == now_ms // 300_000:
                return
        in_list = symbol in {t.symbol for t in self._change_ranked(_FORECAST_TOPN)}
        self._forecast_one_safe(symbol, in_list)
        if self.get_forecast(symbol) is not None and symbol == self._last_detail_sym:   # 판단 보류도 화면 갱신
            cb = self._on_detail_ready_cb
            if cb is not None:
                try:
                    cb(symbol)
                except Exception:
                    pass

    def _start_job(self, name: str, target, *args) -> None:
        """주기 작업 스레드 시작 — 같은 작업이 아직 실행 중이면 건너뜀 (느린 응답·차단 중 겹침 방지, 2026-11-15)."""
        with self._lock:
            if name in self._jobs_running:
                return
            self._jobs_running.add(name)

        def run():
            try:
                target(*args)
            finally:
                with self._lock:
                    self._jobs_running.discard(name)
        threading.Thread(target=run, daemon=True).start()

    def _refresh_spreads(self) -> None:
        """전체 심볼 호가 스프레드 (ask−bid)/mid×100 표본 1개씩 추가 — 조회 실패 시 기존 표본 유지."""
        rows = self._client.fetch_all_book_tickers()
        with self._lock:
            for d in rows:
                sym = d.get("symbol", "")
                try:
                    bid = float(d.get("bidPrice", 0))
                    ask = float(d.get("askPrice", 0))
                except (TypeError, ValueError):
                    continue
                if not sym or bid <= 0 or ask < bid:
                    continue
                hist = self._spread_hist.setdefault(sym, deque(maxlen=_SPREAD_SAMPLES))
                hist.append((ask - bid) / ((ask + bid) / 2) * 100.0)

    def _refresh_funding_window(self) -> None:
        """종목별 (마지막 정산 시각, 다음 정산 시각) 갱신 — premiumIndex 전체 1회(가중치 10) + fundingInfo 1회.
        fundingInfo에 없는 종목은 간격 1시간(최소)으로 본다 → 받은 값이 최신으로 확인되지 않아 매 주기 조회(기존 동작).
        premiumIndex 조회 실패 시 창을 비운다 → 모든 종목 매 주기 조회(기존 동작)."""
        rows  = self._client.fetch_all_premium_index()
        hours = {d.get("symbol", ""): d.get("fundingIntervalHours")
                 for d in self._client.fetch_funding_info()} if rows else {}
        win: dict[str, tuple[int, int]] = {}
        for d in rows:
            try:
                sym = d["symbol"]
                nxt = int(d["nextFundingTime"])
                h   = int(hours.get(sym) or 1)
            except (KeyError, TypeError, ValueError):
                continue
            if nxt > 0 and h > 0:
                win[sym] = (nxt - h * 3_600_000, nxt)
        with self._lock:
            self._fr_window = win

    def _get_funding(self, symbol: str) -> FundingRateData | None:
        """가장 최근 정산 펀딩비 (fundingRate?limit=1 — 백테스트 이력과 같은 정산 값).
        저장 값이 마지막 정산 시각 이후 값이고 다음 정산 전이면 재사용, 아니면 조회
        (정산 직후 새 값 미게시 → 저장 값이 마지막 정산 시각보다 이전 → 다음 호출에서 재조회)."""
        now_ms = time.time() * 1000
        with self._lock:
            cur = self._fr_cache.get(symbol)
            win = self._fr_window.get(symbol)
        if cur is not None and win is not None and cur.funding_time >= win[0] and now_ms < win[1]:
            return cur
        fr = self._fr_svc.fetch(symbol)
        if fr is not None:
            with self._lock:
                self._fr_cache[symbol] = fr
        return fr

    def _refresh_topn_scores(self, n: int = 100) -> None:
        """STAGE2: 상위 N개 심볼 L/S·FR·OI 병렬 갱신 (5스레드, ~15초).
        Sharp Rise·Decline 별점·필터 정확도 및 장 단계 실데이터화.
        """
        tickers = list(self._sorted_tickers[:n])
        self._refresh_funding_window()

        def _one(ticker: "SymbolTicker") -> None:
            rate_gate.defer_if_over_soft_cap()   # 이번 분 IP 사용량 1,900 이상 → 다음 분까지 대기 (2026-11-16)
            if rate_gate.remaining() > 0:   # 차단 중 — 남은 종목 조회 생략 (기존 값 유지)
                return
            sym      = ticker.symbol
            existing = self._ind_cache.get(sym, {})
            try:
                ls = self._ls_svc.fetch(sym)
                fr = self._get_funding(sym)
                oi = self._oi_svc.fetch_change_pct(sym)
                ind = dict(existing) if existing else self._simple_ind(ticker)
                if ls:
                    ind["long_ratio"]   = ls.long_account_pct
                if fr:
                    ind["funding_rate"] = fr.funding_rate * 100.0
                ind["oi_change"] = oi
                ind["_stage2_ready"] = True   # 청산 근접도 계산 조건 (_apply_liq)
                with self._lock:
                    # 네트워크 대기 중 다른 단계가 갱신한 필드를 되돌리지 않도록
                    # 현재 캐시를 기준으로 이 단계 담당 필드만 덮어쓴다.
                    cur = self._ind_cache.get(sym)
                    if cur is not None:
                        merged = dict(cur)
                        merged.update({k: ind[k] for k in _STAGE2_FIELDS if k in ind})
                        ind = merged
                    if sym != self._engine_sym:   # 엔진 종목 청산 값은 상세 경로 값 유지 (엔진 입력 불변)
                        _apply_liq(ind)
                    self._ind_cache[sym] = ind
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=_STAGE2_WORKERS) as pool:
            pool.map(_one, tickers)

    def _refresh_topn_klines(self, n: int = 100) -> None:
        """STAGE3: 상위 N개 심볼 TF klines 병렬 갱신 (7스레드).
        TF정렬·ATR%·EMA·StochRSI·4TF별점·장 단계 실데이터화.
        갱신 TF: 1m·3m·5m·15m·1h·4h·1d (단기·일일 추세 — middle.analysis.trend)
        """
        tickers = list(self._sorted_tickers[:n])
        self._stage3_stale = False

        def _one(ticker: "SymbolTicker") -> None:
            rate_gate.defer_if_over_soft_cap()   # 이번 분 IP 사용량 1,900 이상 → 다음 분까지 대기 (2026-11-16)
            if rate_gate.remaining() > 0:   # 차단 중 — 남은 종목 조회 생략 (기존 값 유지)
                return
            sym      = ticker.symbol
            if sym == self._engine_sym:
                return   # 엔진 종목은 상세 갱신·WS 봉 마감 경로만 사용 (STAGE3 갱신 시점 경합 차단)
            existing = self._ind_cache.get(sym, {})
            try:
                # ── klines 수집 (2026-11-16) ─────────────────
                #   새 마감 봉이 없는 TF는 저장 봉 재사용, 있으면 새 봉만(3개) 받아 이어붙임 — 마감 봉은 바뀌지 않으므로
                #   전체 조회와 같은 목록. 저장 봉 없음·봉 수 다름·이어지지 않음 → 전체 조회.
                now_ms = int(time.time() * 1000)
                with self._lock:
                    cached = dict(self._ohlcv_cache.get(sym, {}))
                bars: dict = {}
                fetched = False
                for tf in _KLINES_TFS:
                    need = _KLINES_LIMITS[tf] - 1          # 마지막(진행 중) 봉 제외 마감 봉 수
                    due  = _latest_close_ms(tf, now_ms)
                    cur  = cached.get(tf)
                    b = None
                    if cur and len(cur) == need:
                        if cur[-1].close_time + 1 >= due:
                            b = cur                        # 새 마감 봉 없음 — 조회 생략
                        else:
                            fetched = True
                            b = _splice_bars(cur, self._ohlcv_svc.fetch(sym, tf, _KLINES_INCR_LIMIT), need)
                    if b is None:
                        fetched = True
                        b = self._ohlcv_svc.fetch(sym, tf, _KLINES_LIMITS[tf]) or cur
                    if b:
                        bars[tf] = b
                        if b[-1].close_time + 1 < due:
                            self._stage3_stale = True      # 새 봉 미게시(또는 조회 실패) — 같은 분 안 재시도
                if not bars:
                    return
                if not fetched and existing.get("_data_ready"):
                    return                                 # 재시도 실행에서 이미 최신인 종목 — 계산 생략

                b1h = bars.get("1h", [])
                b5m = bars.get("5m", [])
                b5m_w = b5m[-_VWAP_ATR5M_BARS_TOPN:]   # VWAP·5m ATR% 기존 창

                # ── 지표 계산 ────────────────────────────────
                atr    = AtrPercent.calculate(b1h) if b1h              else 2.0
                atr_5m = AtrPercent.calculate(b5m_w) if len(b5m_w) >= 15  else 0.0
                ema = EMAAlignment.calculate(b1h) if b1h else None
                vwap_r = VWAP.calculate(b5m_w or b1h) if (b5m_w or b1h) else None
                pat  = CandlePattern.detect(b5m or b1h) if (b5m or b1h) else "분석 중 …"

                stoch:        dict[str, StochRSIResult] = {}
                stoch_series: dict[str, list[float]]   = {}
                for tf, b in bars.items():
                    stoch[tf], stoch_series[tf] = StochRSI.calculate_with_series(b)

                # ── ind 업데이트 (기존 캐시 기반) ────────────
                ind = dict(existing) if existing else self._simple_ind(ticker)

                ind["atr"]        = atr
                ind["atr_pct"]    = atr
                ind["atr_pct_5m"] = atr_5m
                vss = VSS.calculate(b5m or b1h) if (b5m or b1h) else 1.0
                bpr = BPR.from_candles(b1h)     if b1h           else 0.5
                ind["vss"]              = round(vss, 4)
                ind["bpr"]              = round(bpr, 4)
                ind["price_change_pct"] = round(ticker.price_change_pct, 4)
                ind["pattern"] = pat

                if ema:
                    ind["align"] = ema.align
                    ind["e5"]    = ema.ema5
                    ind["e10"]   = ema.ema10
                    ind["e20"]   = ema.ema20
                    ind["e50"]   = ema.ema50

                # volume_ratio — 1m 최근 봉 / 20봉 평균
                b1m_kr = bars.get("1m", [])
                if len(b1m_kr) >= 21:
                    # 현재봉 제외 — backtest_runner._calc_vol_ratio_series 와 동일 정의
                    avg_vol = sum(b.volume for b in b1m_kr[-21:-1]) / 20.0
                    ind["volume_ratio"] = b1m_kr[-1].volume / avg_vol if avg_vol > 0 else 1.0
                else:
                    ind["volume_ratio"] = 1.0

                # swing_bull / swing_bear — 15m 봉 고/저가 구조
                b15m_kr = bars.get("15m", [])
                sw_bull = sw_bear = False
                if len(b15m_kr) >= 6:
                    h = [b.high for b in b15m_kr[-6:]]
                    l = [b.low  for b in b15m_kr[-6:]]
                    sw_bull = (h[-1] > h[-3] > h[-5]) and (l[-1] > l[-3] > l[-5])
                    sw_bear = (h[-1] < h[-3] < h[-5]) and (l[-1] < l[-3] < l[-5])
                ind["swing_bull"] = sw_bull
                ind["swing_bear"] = sw_bear

                if vwap_r:
                    ind["vwap"] = vwap_r.label

                # StochRSI tf 딕셔너리 업데이트
                tf_key_map = {
                    "1m":  "tf1",  "3m":  "tf3",
                    "5m":  "tf5",  "15m": "tf15",
                    "1h":  "tf1h", "4h":  "tf4h", "1d":  "tf1d",
                }
                for tf, key in tf_key_map.items():
                    if tf in stoch:
                        r       = stoch[tf]
                        old_dir = existing.get(key, {}).get("dir", "↔")
                        elapsed = self._resolve_elapsed(sym, key, r.direction, old_dir)
                        div     = DivergenceDetector.detect(
                                      bars[tf], stoch_series.get(tf, []))
                        ks = stoch_series.get(tf, [])
                        ds = StochRSI._sma(ks, StochRSI.SMOOTH_D) if len(ks) >= StochRSI.SMOOTH_D else []
                        ind[key] = {
                            "dir": r.direction, "col": _dir_col(r.direction),
                            "k": r.k, "d": r.d,
                            "elapsed": elapsed, "div": div,
                            "k_series": ks[-40:], "d_series": ds[-40:],
                            "recent_volumes": ([b.volume for b in bars.get("5m", [])[-21:]]
                                               if key == "tf5" else []),
                        }

                ind["_data_ready"] = True
                with self._lock:
                    if _has_newer(self._ohlcv_cache.get(sym, {}), bars):
                        return   # 수집 중 더 최신 봉이 반영됨 — 이번 STAGE3 결과로 되돌리지 않음
                    # 네트워크 대기 중 다른 단계가 갱신한 필드를 되돌리지 않도록
                    # 현재 캐시를 기준으로 이 단계 담당 필드만 덮어쓴다.
                    cur = self._ind_cache.get(sym)
                    if cur is not None:
                        merged = dict(cur)
                        merged.update({k: ind[k] for k in _STAGE3_FIELDS if k in ind})
                        ind = merged
                    _apply_liq(ind)   # 엔진 종목은 STAGE3 대상 아님 (함수 첫머리에서 제외)
                    self._ind_cache[sym] = ind
                    sym_cache = self._ohlcv_cache.setdefault(sym, {})
                    sym_cache.update(bars)

            except Exception as e:
                with self._lock:
                    self._last_refresh_error      = f"[stage3:{sym}] {e}"
                    self._last_refresh_error_time = time.time()
                logging.warning("middle STAGE3 %s: %s", sym, e)

        with ThreadPoolExecutor(max_workers=_STAGE3_WORKERS) as pool:
            pool.map(_one, tickers)
        self._stage3_done = True   # 시작 후 첫 완료 → 예고 판정 시작 가능

        # STAGE3 완료 콜백 → TF합의·ATR%·EMA 즉시 UI 반영
        cb = self._on_klines_ready_cb
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _on_ws_ticker_update(self, tickers: list) -> None:
        """WebSocket 1초 Push 수신 콜백.
        _tickers / _tkr_map / _sorted_tickers 갱신 → 소프트 UI 업데이트.
        5회(5초)마다 _rebuild_ranking_rows() 실행 (Sharp/4TF 모드 풀 갱신).

        !miniTicker@arr는 변경된 심볼만 담으므로(실측 747개 중 메시지당 136~361개) 기존 목록에 병합한다.
        시작 시 REST(_refresh_tickers)가 채운 전체 목록을 유지하고, REST와 같은 기준으로
        TRADING 심볼만 남긴다(_get_trading_symbols 5분 캐시 — 거래정지·상장폐지 심볼 제거).
        """
        if not tickers:
            return
        trading = self._client._get_trading_symbols()
        with self._lock:
            merged = dict(self._tkr_map)
            for t in tickers:
                merged[t.symbol] = t
            if trading:
                merged = {s: t for s, t in merged.items() if s in trading}
            all_tickers = list(merged.values())
            sorted_vol  = sorted(all_tickers, key=lambda t: t.volume_usdt, reverse=True)
            self._tickers        = all_tickers
            self._sorted_tickers = sorted_vol
            self._tkr_map        = merged
            self._vol_rank       = {t.symbol: i + 1 for i, t in enumerate(sorted_vol)}

        # 5회(=5초)마다 ranking_rows 재빌드 (Sharp/4TF 모드용)
        self._ws_update_count += 1
        if self._ws_update_count % 5 == 0:
            self._rebuild_ranking_rows()
            if self._ws_update_count >= 300:   # 5분(300초)마다 카운터 리셋
                self._ws_update_count = 0

        # UI 소프트 갱신 콜백 (1초마다 Change% 숫자 업데이트)
        cb = self._on_ranking_ready_cb
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _on_kline_closed(self, symbol: str, tf: str, bar: OHLCVBar) -> None:
        """WebSocket klines 봉 마감 콜백 — 마감 봉 최종값을 캐시에 즉시 접합 후 지표 재계산 (REST 없음).

        캐시·파생 데이터가 없거나 봉이 이어지지 않으면(누락) REST 상세 갱신으로 보완.
        """
        with self._lock:
            if symbol not in (self._engine_sym, self._last_detail_sym):
                return
            cached = self._ohlcv_cache.get(symbol, {})
            cur    = cached.get(tf)
            deriv  = self._deriv_cache.get(symbol)
            bars: dict | None = None
            if cur and deriv is not None and all(cached.get(t) for t in _DETAIL_TFS):
                last = cur[-1]
                if bar.close_time <= last.close_time:
                    return                                   # 이미 반영된 봉
                if bar.open_time == last.close_time + 1:
                    bars = dict(cached)
                    bars[tf] = cur[1:] + [bar]               # 봉 수 유지 — 지표 계산 창 불변
        if bars is None:
            threading.Thread(target=self._refresh_detail, args=(symbol,), daemon=True).start()
            return
        self._compute_detail(symbol, bars, *deriv)

    def _refresh_tickers(self) -> None:
        try:
            tickers = self._tkr_svc.fetch_all()
            if not tickers:
                # 조회 실패(네트워크·5xx·429 → 빈 응답): 직전 시세 유지 — 덮어쓰면 1열 목록이 비고, WS 복구 뒤에도
                # 바뀐 종목만 다시 채워져 일부 종목 순위가 됨 (2026-11-16)
                with self._lock:
                    kept = len(self._tickers)
                logging.warning("middle _refresh_tickers: REST 시세 빈 응답 — 직전 시세 유지 (%d종목)", kept)
                return
            # 거래량 내림차순 정렬 — 다른 Sort by 모드의 스코어링 풀로 사용
            sorted_vol = sorted(tickers, key=lambda t: t.volume_usdt, reverse=True)
            vol_rank = {t.symbol: i + 1 for i, t in enumerate(sorted_vol)}
            with self._lock:
                self._tickers         = tickers          # API 응답 원본 (전체)
                self._sorted_tickers  = sorted_vol       # 거래량 내림차순 (전체)
                self._tkr_map         = {t.symbol: t for t in tickers}
                self._vol_rank        = vol_rank
                self._last_tkr_refresh = time.time()
                self._tickers_full_loaded = True
            self._rebuild_ranking_rows()
            # 5초 ticker 갱신 완료 콜백 → middle_panel 경량 랭킹 업데이트
            cb = self._on_ranking_ready_cb
            if cb is not None:
                try:
                    cb()   # → middle_panel._soft_update_ranking()
                except Exception:
                    pass
        except Exception as e:
            logging.warning("middle _refresh_tickers: %s", e)

    def _rebuild_ranking_rows(self) -> None:
        """Sharp Rise/Decline/Volatility/4TF 모드용 랭킹 풀 빌드.
        거래량 상위 200개 기준 — 유동성 높은 심볼 우선.
        (24h Ticker 모드는 get_all_ranked_by_change() 별도 사용)
        """
        with self._lock:
            # 거래량 정렬된 상위 200개 (기존: API 응답 순서 첫 200개 → 수정)
            tickers_snap = list(self._sorted_tickers[:200])
        use_macro = self._m4_use_macro()
        rows = [self._make_row(t, use_macro) for t in tickers_snap]
        with self._lock:
            self._ranking_rows = rows

    def get_all_ranked_by_change(self, limit: int = 100) -> list:
        """24h Ticker 모드 전용: 전체 심볼 변동률 내림차순 top N 반환 (블랙리스트 먼저 제외 — _change_ranked).
        tickers[:200] 절단 없이 전체에서 가장 많이 오른 심볼 표시.
        """
        use_macro = self._m4_use_macro()
        return [self._make_row(t, use_macro) for t in self._change_ranked(limit)]

    def _change_ranked(self, limit: int) -> list[SymbolTicker]:
        """24h 변동률 내림차순 상위 limit — 블랙리스트를 먼저 빼고 자른다 (항상 limit개, 2026-11-12).
        1열 24h Ticker 목록과 가격 예고 '목록' 조건의 단일 정의."""
        with self._lock:
            tickers_snap = list(self._tickers)   # 전체 원본 복사
        tickers_snap = [t for t in tickers_snap if not self._list_excluded(t.symbol)]
        tickers_snap.sort(key=lambda t: t.price_change_pct, reverse=True)
        return tickers_snap[:limit]

    def get_newlisted_rows(self) -> list:
        """Newly Listed 모드 전용: 전체 _tickers에서 상장 30일 이내 심볼만 행 반환.
        get_ranking_rows()의 거래량 상위 200개 제한 없이 전체 유니버스 탐색.
        """
        with self._lock:
            tickers_snap = list(self._tickers)
            onboard_snap = dict(self._onboard_map)
        use_macro = self._m4_use_macro()
        result = []
        for t in tickers_snap:
            ob = onboard_snap.get(t.symbol, 0)
            if not ob:
                continue
            days = _days_since_listing(ob)
            if 0 < days <= 30:
                result.append(self._make_row(t, use_macro))
        return result

    def _fetch_onboard_map(self) -> None:
        try:
            ei = self._client.fetch_exchange_info()
            if ei:
                m = _build_onboard_map(ei)
                with self._lock:
                    self._onboard_map = m
        except Exception:
            pass

    def _refresh_detail(self, symbol: str) -> None:
        """선택 심볼 전체 지표 갱신 (REST)."""
        try:
            # OHLCV 7 TF 병렬 수집
            with ThreadPoolExecutor(max_workers=len(_DETAIL_TFS)) as ex:
                futs = {tf: ex.submit(self._ohlcv_svc.fetch, symbol, tf, _KLINES_LIMITS[tf])
                        for tf in _DETAIL_TFS}
                bars: dict[str, list[OHLCVBar]] = {tf: fut.result() for tf, fut in futs.items()}

            # 파생 데이터
            fr  = self._get_funding(symbol)
            oi  = self._oi_svc.fetch_change_pct(symbol)
            ls  = self._ls_svc.fetch(symbol)

            with self._lock:
                self._deriv_cache[symbol] = (fr, oi, ls)
                # 단조 가드 — WS로 이미 반영된 더 최신 봉을 REST 응답(마감 직후 이전 봉까지)으로 되돌리지 않음
                cached = self._ohlcv_cache.get(symbol, {})
                for tf in _DETAIL_TFS:
                    cb = cached.get(tf)
                    if cb and (not bars.get(tf) or cb[-1].close_time > bars[tf][-1].close_time):
                        bars[tf] = cb
        except Exception as e:
            with self._lock:
                self._last_refresh_error      = f"[detail:{symbol}] {e}"
                self._last_refresh_error_time = time.time()
            logging.warning("middle detail %s: %s", symbol, e)
            return
        self._compute_detail(symbol, bars, fr, oi, ls)

    def _compute_detail(self, symbol: str, bars: dict, fr, oi, ls) -> None:
        """봉·파생 데이터로 상세 지표 계산 후 캐시 반영 — REST 갱신·WS 봉 마감 접합 공용."""
        try:
            # 지표 계산 (1h 기준)
            b1h  = bars.get("1h", [])
            b5m  = bars.get("5m", [])
            b5m_w = b5m[-_VWAP_ATR5M_BARS_DETAIL:]   # VWAP·5m ATR% 기존 창
            rsi  = RSI.calculate(b1h)
            bpr  = BPR.from_candles(b1h)
            vss  = VSS.calculate(b5m or b1h)
            atr    = AtrPercent.calculate(b1h)
            atr_5m = AtrPercent.calculate(b5m_w) if len(b5m_w) >= 15 else 0.0
            ema  = EMAAlignment.calculate(b1h)
            vwap_r = VWAP.calculate(b5m_w or b1h)
            pat  = CandlePattern.detect(b5m or b1h)

            # StochRSI 7 TF
            stoch:        dict[str, StochRSIResult] = {}
            stoch_series: dict[str, list[float]]   = {}
            for tf, b in bars.items():
                stoch[tf], stoch_series[tf] = StochRSI.calculate_with_series(b)

            # 파생 값
            fr_pct   = fr.funding_rate * 100.0 if fr else 0.0
            long_pct = ls.long_account_pct  if ls else 50.0
            oi_chg   = oi

            # 청산 근접도
            liq = LiquidationProximityPanel.estimate(atr, fr_pct, long_pct)

            # ticker (price_chg_pct 전달을 위해 앞으로 이동)
            tkr = self._tkr_map.get(symbol)
            price_chg = tkr.price_change_pct if tkr else 0.0

            # Player Detection
            det = TagDetector.detect(
                long_pct=long_pct, fr_pct=fr_pct,
                oi_change_pct=oi_chg, vss=vss, bpr=bpr, atr_pct=atr,
                price_chg_pct=price_chg,
            )

            # 에너지 균형
            eb = EnergyBalance.calculate(
                bpr=bpr, rsi_1h=rsi,
                vwap_above=(vwap_r.position == "above"),
                stochrsi_k_1h=stoch.get("1h", StochRSI.calculate([])).k,
            )

            # 권장 레버리지
            lev = RecommendedLeverage.calculate(atr, long_pct, eb.long_ratio)

            # ind dict 구성
            ind = self._build_ind_dict(
                symbol=symbol, tkr=tkr, bars=bars, stoch=stoch,
                stoch_series=stoch_series,
                rsi=rsi, bpr=bpr, vss=vss, atr=atr, atr_5m=atr_5m, ema=ema,
                vwap_r=vwap_r, pat=pat, fr_pct=fr_pct, oi_chg=oi_chg,
                long_pct=long_pct, liq=liq, lev=lev.leverage,
                player_keys=list(det.keys), eb=eb,
            )

            # volume_ratio — 1m 최근 봉 / 20봉 평균
            b1m_d = bars.get("1m", [])
            if len(b1m_d) >= 21:
                # 현재봉 제외 — backtest_runner._calc_vol_ratio_series 와 동일 정의
                avg_v = sum(b.volume for b in b1m_d[-21:-1]) / 20.0
                ind["volume_ratio"] = b1m_d[-1].volume / avg_v if avg_v > 0 else 1.0
            else:
                ind["volume_ratio"] = 1.0

            # swing_bull / swing_bear — 15m 봉 고/저가 구조
            b15m_d = bars.get("15m", [])
            s_bull = s_bear = False
            if len(b15m_d) >= 6:
                hd = [b.high for b in b15m_d[-6:]]
                ld = [b.low  for b in b15m_d[-6:]]
                s_bull = (hd[-1] > hd[-3] > hd[-5]) and (ld[-1] > ld[-3] > ld[-5])
                s_bear = (hd[-1] < hd[-3] < hd[-5]) and (ld[-1] < ld[-3] < ld[-5])
            ind["swing_bull"] = s_bull
            ind["swing_bear"] = s_bear

            with self._lock:
                if _has_newer(self._ohlcv_cache.get(symbol, {}), bars):
                    return   # 계산 중 더 최신 봉이 반영됨 — 그 결과 유지
                self._ind_cache[symbol] = ind
                self._ohlcv_cache[symbol] = bars

            # Fix②: 실데이터 준비 완료 콜백 — after(0)으로 메인 스레드에 위임
            # cb 자체가 after() 를 호출하므로 백그라운드에서 호출해도 안전
            cb = self._on_detail_ready_cb
            if cb is not None:
                try:
                    cb(symbol)   # → middle_panel._on_data_ready(symbol)
                except Exception:
                    pass         # 위젯 삭제/None 상황 무시

        except Exception as e:
            with self._lock:
                self._last_refresh_error      = f"[detail:{symbol}] {e}"
                self._last_refresh_error_time = time.time()
            logging.warning("middle detail %s: %s", symbol, e)

    # ══ dict 빌더 ═════════════════════════════════════════════

    def _build_ind_dict(
        self, symbol, tkr, bars, stoch,
        stoch_series,
        rsi, bpr, vss, atr, atr_5m, ema, vwap_r, pat,
        fr_pct, oi_chg, long_pct, liq, lev,
        player_keys, eb,
    ) -> dict:
        price = tkr.last_price if tkr else 1.0
        chg   = tkr.price_change_pct if tkr else 0.0

        # tf dict 매핑 (mockup 키 → 실제 TF)
        tf_key_map = {
            "tf1": "1m", "tf3": "3m", "tf5": "5m", "tf15": "15m",
            "tf1h": "1h", "tf4h": "4h", "tf1d": "1d",
        }

        d: dict = {
            # 기술 지표
            "rsi":     round(rsi, 2),
            "bpr":     round(bpr, 4),
            "vss":     round(vss, 4),
            "atr":        atr,      # SYMBOL_IND에서 "atr" 키 사용
            "atr_pct":    atr,      # 두 이름 모두 지원
            "atr_pct_5m": atr_5m,   # 5m ATR% — SL 자동 계산용
            # EMA
            "e5":    ema.ema5,
            "e10":   ema.ema10,
            "e20":   ema.ema20,
            "e50":   ema.ema50,
            "align": ema.align,
            # VWAP
            "vwap":   vwap_r.label,
            # 캔들 패턴
            "pattern": pat,
            # 펀딩비 (% 단위, SYMBOL_IND 포맷 호환)
            "funding_rate": fr_pct,
            # OI 변화 %
            "oi_change": round(oi_chg, 2),
            # 롱숏 비율
            "long_ratio": round(long_pct, 2),
            # 청산 근접도 (추정)
            "liq_long_pct":  liq.liq_long_pct,
            "liq_short_pct": liq.liq_short_pct,
            # 권장 레버리지
            "rec_leverage": lev,
            # 차트용
            "base":  round(price, 8),
            "trend": 0.0,
            # 신규 상장 생애주기용
            "price_change_pct": round(chg, 4),
            "high_24h_pct":     round((tkr.high_24h - price) / price * 100, 2)
                                if tkr and price > 0 else 0.0,
            # 거래량
            "volume": {
                "rank":  self._vol_rank.get(symbol, 999),
                "usd_b": round((tkr.volume_usdt / 1e9) if tkr else 0.0, 3),
            },
            # 에너지
            "_energy_long_ratio": round(eb.long_ratio, 4),
            # Player 태그 (내부용) — _player_keys: 절단 전 전체 키 (엔진 금지 조건)
            #   상세 갱신에서만 생성 — 없으면 엔진은 Player 판정 데이터 미준비로 진입 보류
            #   (화면 표시 태그는 get_player 단일 정의 사용)
            "_player_keys": player_keys,
            "_data_ready":  True,
        }

        # StochRSI TF dict 추가 (실제 교차 시점 기반 elapsed)
        cached_ind = self._ind_cache.get(symbol, {})
        for tf_key, tf_real in tf_key_map.items():
            r = stoch.get(tf_real)
            if r is None:
                d[tf_key] = {"dir": "↔", "col": _YEL, "k": 50.0, "d": 50.0,
                             "elapsed": None, "div": None,
                             "k_series": [], "d_series": [], "recent_volumes": []}
            else:
                old_dir = cached_ind.get(tf_key, {}).get("dir", "↔")
                elapsed = self._resolve_elapsed(symbol, tf_key, r.direction, old_dir)
                div     = DivergenceDetector.detect(
                              bars.get(tf_real, []), stoch_series.get(tf_real, []))
                ks = stoch_series.get(tf_real, [])
                ds = StochRSI._sma(ks, StochRSI.SMOOTH_D) if len(ks) >= StochRSI.SMOOTH_D else []
                d[tf_key] = {"dir": r.direction, "col": _dir_col(r.direction),
                             "k": r.k, "d": r.d,
                             "elapsed": elapsed, "div": div,
                             "k_series": ks[-40:], "d_series": ds[-40:],
                             "recent_volumes": ([b.volume for b in bars.get(tf_real, [])[-21:]]
                                                if tf_key == "tf5" else [])}

        return d

    def _simple_ind(self, tkr: SymbolTicker) -> dict:
        """ticker 데이터만으로 생성하는 최소 ind dict."""
        chg_dir = "▲" if tkr.price_change_pct > 0 else "▼" if tkr.price_change_pct < 0 else "↔"
        tf_default = _stoch_tf_dict(None)
        d: dict = {
            "rsi": 50.0, "bpr": 0.5, "vss": 1.0, "atr": 2.0, "atr_pct": 2.0, "atr_pct_5m": 0.0,
            "e5": tkr.last_price, "e10": tkr.last_price, "e20": tkr.last_price,
            "e50": tkr.last_price,
            "align": "혼조", "vwap": "VWAP 근접", "pattern": "분석 중 …",
            "funding_rate": 0.0, "oi_change": 0.0, "long_ratio": 50.0,
            "price_change_pct": round(tkr.price_change_pct, 4),
            "liq_long_pct": -2.0, "liq_short_pct": 2.0, "rec_leverage": 10,
            "base": tkr.last_price, "trend": 0.0,
            "volume": {"rank": self._vol_rank.get(tkr.symbol, 999),
                       "usd_b": round(tkr.volume_usdt / 1e9, 3)},
            "_energy_long_ratio": 0.5,
            "_days_listed": 9999,
            "volume_ratio": 1.0,
            "swing_bull": False,
            "swing_bear": False,
            "_data_ready":  False,
        }
        for k in ("tf1","tf3","tf5","tf15","tf1h","tf4h","tf1d"):
            d[k] = dict(tf_default)
        return d

    def _default_ind(self) -> dict:
        """심볼 정보 없을 때 반환할 기본 ind dict."""
        tf_default = _stoch_tf_dict(None)
        d: dict = {
            "rsi": 50.0, "bpr": 0.5, "vss": 1.0, "atr": 2.0, "atr_pct": 2.0, "atr_pct_5m": 0.0,
            "e5": 100.0, "e10": 99.0, "e20": 98.0, "e50": 97.0,
            "align": "혼조", "vwap": "VWAP 근접", "pattern": "분석 중 …",
            "funding_rate": 0.0, "oi_change": 0.0, "long_ratio": 50.0,
            "liq_long_pct": -2.0, "liq_short_pct": 2.0, "rec_leverage": 10,
            "base": 100.0, "trend": 0.0,
            "volume": {"rank": 999, "usd_b": 0.0},
            "_energy_long_ratio": 0.5,
            "_days_listed": 9999,
            "volume_ratio": 1.0,
            "swing_bull": False,
            "swing_bear": False,
            "_data_ready":  False,
        }
        for k in ("tf1","tf3","tf5","tf15","tf1h","tf4h","tf1d"):
            d[k] = dict(tf_default)
        return d

    # ══ 랭킹 행 빌더 ══════════════════════════════════════════════

    def _make_row(self, tkr: SymbolTicker, use_macro: bool) -> tuple:
        """ticker → 실데이터 11-tuple 랭킹 행 생성.
        use_macro: 1열 Sort by와 이름이 같은 엔진 모드의 G7.5 적용 여부 (_m4_use_macro)."""
        sym  = tkr.symbol
        chg  = tkr.price_change_pct

        # [1] 신규 상장 days
        days = self.get_listing_days(sym)

        # [2,3] M4 진입 준비 상태 (G2 15m RSI 50 + G7.5 거시 점수) — 엔진 M4Entry와 같은 판정
        # 갱신 대상 밖 종목의 남은 캐시(옛 값)는 쓰지 않음 → '데이터 없음'·추세 단계는 24h 변동률 구간 (_ind_fresh)
        fresh = self._ind_fresh(sym)
        ind = self._ind_cache.get(sym) if fresh else None
        b15 = self._ohlcv_cache.get(sym, {}).get("15m", []) if fresh else []
        rsi15: float | None = None
        if ind and len(b15) >= _G2_RSI_BARS:
            # G2: 엔진·백테스트와 같은 15m 마감 봉 19개 RSI(14) — 엔진도 이 캐시(get_ohlcv)를 사용
            _rsi_list = calc_rsi_series([b.close for b in b15[-_G2_RSI_BARS:]], period=14)
            if _rsi_list:
                rsi15 = _rsi_list[-1]
        if rsi15 is not None:
            # G7.5: 거시 추세 점수 -3~+3 (M4Entry G7.5 게이트 동일 로직)
            macro_score = 0
            for _tf in ("tf1h", "tf4h", "tf1d"):
                _k  = ind.get(_tf, {}).get("k", 50.0)
                _d  = ind.get(_tf, {}).get("d", 50.0)
                _sp = _k - _d
                if   _sp >=  2.0: macro_score += 1
                elif _sp <= -2.0: macro_score -= 1

            if rsi15 > 50.0:            # G2 롱만 통과
                if use_macro and macro_score <= -1:
                    align_txt = "▲ 거시차단"
                    align_col = _ORA
                else:
                    align_txt = "▲ 롱 대기"
                    align_col = _POS
            elif rsi15 < 50.0:          # G2 숏만 통과
                if use_macro and macro_score >= 1:
                    align_txt = "▼ 거시차단"
                    align_col = _YEL
                else:
                    align_txt = "▼ 숏 대기"
                    align_col = _NEG
            else:                       # RSI 정확히 50 — 엔진 G2 롱·숏 모두 통과
                align_txt = "↔ 중립"
                align_col = _DIM
        elif self._vol_rank.get(sym, 999) <= _STAGE2_TOPN:
            align_txt = "─ 로딩중"      # 갱신 대상(거래량 상위 100) — 다음 STAGE3 완료 시 표시
            align_col = _DIM
        else:
            align_txt = "─ 데이터 없음"  # 갱신 대상 밖 — 15m 봉·지표를 계산하지 않음
            align_col = _DIM

        # [4,5] 24h 변동률
        chg_txt = f"  {chg:+.2f}%"
        chg_col = _POS if chg > 0 else (_NEG if chg < 0 else _DIM)

        # [6,7] Cumulative (세션 중 누적 — 단순화: 24h 변동률 사용)
        cum_txt = f"{chg:+.2f}%"
        cum_col = chg_col

        # [8,9,10] 장 단계 (EMA 정배열/역배열 기반)
        ema_align = ind.get("align", "혼조") if ind else "혼조"
        if ema_align == "정배열":
            phase_txt, phase_col, prio = "▲▲ 상승 진행", _POS, 3
        elif ema_align == "역배열":
            phase_txt, phase_col, prio = "▼▼ 하락 진행", _NEG, 3
        elif chg > 5:
            phase_txt, phase_col, prio = "▲! 급등 진행",  _ORA, 5
        elif chg < -5:
            phase_txt, phase_col, prio = "▼! 급락 진행",  _ORA, 5
        elif chg > 2:
            phase_txt, phase_col, prio = "▲ 상승 초기",   _LGR, 2
        elif chg < -2:
            phase_txt, phase_col, prio = "▼ 하락 초기",   _NEG, 2
        else:
            phase_txt, phase_col, prio = "⟳ 전환 대기",   _YEL, 4

        return (sym, days,
                align_txt, align_col,
                chg_txt, chg_col,
                cum_txt, cum_col,
                phase_txt, phase_col,
                prio)

