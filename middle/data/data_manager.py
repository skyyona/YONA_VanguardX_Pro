"""
middle/data/data_manager.py
중단 모듈 실데이터 코디네이터 (DataManager)

역할:
  · 전체 ticker 주기적 갱신 (30초마다, 백그라운드 스레드)
  · 선택된 심볼 상세 데이터 온디맨드 갱신
  · get_ind(symbol) → SYMBOL_IND 포맷 dict  (middle_panel.py 하위 호환)
  · get_ranking_rows() → 실데이터 랭킹 행 목록 (12-tuple 리스트)
  · get_ohlcv(symbol, interval, n) → generate_ohlcv() 호환 dict 리스트
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

# ── 배경 갱신 주기 상수 ────────────────────────────────────────
_TICKER_INTERVAL_SEC = 5   # ticker 갱신 (초) — 5초마다 전체 변동률 갱신
_STAGE2_INTERVAL = 15    # 경량 갱신: L/S·FR·OI (초)
_STAGE3_INTERVAL = 60    # klines 갱신: 4TF OHLCV+지표 (초)
_LOOP_BASE       = 5     # 루프 기본 단위 (초) — TICKER_INTERVAL과 동기화
_STAGE2_WORKERS  = 5     # 경량 갱신 병렬 스레드 수 (3→5: 15초 주기 여유 확보)
_STAGE3_WORKERS  = 7     # klines 갱신 병렬 스레드 수 (3→7: 34초→15초, Rate 36% 유지)
# STAGE3에서 갱신할 TF (1m·3m·5m·15m·1h·4h·1d — 4TF거시지지 s_macro 정확도 확보)
_KLINES_TFS      = ("1m", "3m", "5m", "15m", "1h", "4h", "1d")

from middle.api.binance_client import MiddleBinanceClient
from middle.data.ticker_data import TickerData
from middle.data.websocket_ticker import WebSocketTicker
from middle.data.ohlcv_data import OHLCVData
from middle.data.funding_rate_data import FundingRateFetcher
from middle.data.open_interest_data import OpenInterestFetcher
from middle.data.longshort_data import LongShortFetcher
from middle.models import OHLCVBar, SymbolTicker

from middle.col3_analysis_panels.technical_analysis.rsi import RSI
from middle.col3_analysis_panels.technical_analysis.bpr import BPR
from middle.col3_analysis_panels.technical_analysis.vss import VSS
from middle.col3_analysis_panels.technical_analysis.atr_percent import AtrPercent
from middle.col3_analysis_panels.technical_analysis.ema_alignment import EMAAlignment
from middle.col3_analysis_panels.technical_analysis.vwap import VWAP
from middle.col3_analysis_panels.technical_analysis.candle_pattern import CandlePattern
from middle.col2_chart_indicators.mtf_stochrsi import StochRSI, StochRSIResult
from middle.col2_chart_indicators.divergence_detector import DivergenceDetector
from middle.col3_analysis_panels.derivative_analysis.liquidation_proximity import LiquidationProximityPanel
from middle.col3_analysis_panels.comprehensive_analysis.recommended_leverage import RecommendedLeverage
from middle.col3_analysis_panels.player_detection.tag_detector import TagDetector
from middle.col3_analysis_panels.player_detection.energy_balance import EnergyBalance
from middle.col1_ranking_blacklist.ranking.newlisted_scorer import NewlistedScorer

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


def _stoch_tf_dict(r: StochRSIResult | None) -> dict:
    """StochRSIResult → tf dict (SYMBOL_IND 포맷)."""
    if r is None:
        return {"dir": "↔", "col": _YEL, "k": 50.0, "d": 50.0,
                "elapsed": None, "div": None,
                "k_series": [], "d_series": []}
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
        self._onboard_map:     dict[str, int]             = {}
        self._cross_ts_cache:  dict[str, dict[str, float]] = {}  # sym→{tf_key→교차 unix ts}

        # ── 상태 ───────────────────────────────────────────────
        self._last_tkr_refresh: float = 0.0
        # Fix②: 실데이터 준비 완료 시 화면 재갱신 콜백 (middle_panel이 등록)
        self._on_detail_ready_cb:  "callable | None" = None   # 심볼 상세 갱신 콜백
        self._on_ranking_ready_cb: "callable | None" = None   # ticker 갱신 완료 콜백
        self._on_klines_ready_cb:  "callable | None" = None   # STAGE3 완료 콜백 → TF합의 즉시 반영
        self._last_detail_sym:  str   = ""
        self._last_detail_time: float = 0.0
        self._lock = threading.Lock()
        # WebSocket 실시간 ticker (1초 Push)
        self._ws_ticker: WebSocketTicker | None = None
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
        # 캐시 초기화 — STOP 후 재START 시 신선한 데이터
        with self._lock:
            self._tickers.clear()
            self._sorted_tickers.clear()
            self._tkr_map.clear()
            self._ind_cache.clear()
            self._ohlcv_cache.clear()
            self._ranking_rows.clear()
            self._cross_ts_cache.clear()

    def request_selected(self, symbol: str) -> None:
        """선택 심볼 상세 데이터 비동기 갱신 요청."""
        now = time.time()
        if (symbol == self._last_detail_sym
                and now - self._last_detail_time < _DETAIL_COOLDOWN):
            return
        self._last_detail_sym  = symbol
        self._last_detail_time = now
        threading.Thread(target=self._refresh_detail, args=(symbol,), daemon=True).start()

    def get_ind(self, symbol: str) -> dict:
        """SYMBOL_IND 포맷 dict 반환 (캐시 우선, 없으면 ticker 기반 기본값)."""
        cached = self._ind_cache.get(symbol)
        if cached:
            ob = self._onboard_map.get(symbol, 0)
            cached["_days_listed"] = (
                NewlistedScorer.get_days_since_listing(ob) if ob else 9999
            )
            return cached
        tkr = self._tkr_map.get(symbol)
        if tkr:
            return self._simple_ind(tkr)
        return self._default_ind()

    def get_ranking_rows(self) -> list:
        """실데이터 랭킹 행 목록 반환 (12-tuple 리스트)."""
        if self._ranking_rows:
            return self._ranking_rows
        # 캐시 없으면 ticker 기반 즉시 생성
        return [self._make_row(t) for t in self._tickers[:200]]

    def get_ohlcv(self, symbol: str, interval: str = "5m", n: int = 60) -> list[dict]:
        """generate_ohlcv() 호환 dict 리스트 반환."""
        bars = self._ohlcv_cache.get(symbol, {}).get(interval, [])
        if not bars:
            try:
                bars = self._ohlcv_svc.fetch(symbol, interval, max(n, 60))
                sym_cache = self._ohlcv_cache.setdefault(symbol, {})
                sym_cache[interval] = bars
            except Exception:
                bars = []
        return [{"o": b.open, "h": b.high, "l": b.low,
                 "c": b.close, "v": b.quote_volume} for b in bars[-n:]]

    def get_player_tags(self, symbol: str) -> list:
        """(tag_text, tag_color, strength_pct) 목록 반환."""
        return self._ind_cache.get(symbol, {}).get("_player_tags", [])

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
        STAGE2: 15초마다 — L/S·FR·OI 경량 갱신 → Sharp 별점·필터 정확도
        STAGE3: 60초마다 — 4TF klines 갱신 → TF정렬·ATR%·EMA·4TF별점
        STAGE1: 클릭 즉시 — request_selected() 에서 처리
        """
        # ── 초기 실행 ─────────────────────────────────────────
        self._refresh_tickers()
        self._fetch_onboard_map()
        threading.Thread(target=self._refresh_topn_scores, args=(100,), daemon=True).start()
        threading.Thread(target=self._refresh_topn_klines,  args=(100,), daemon=True).start()

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
            if _elapsed % _TICKER_INTERVAL_SEC == 0:
                if self._ws_ticker is None or not self._ws_ticker.has_received_data:
                    self._refresh_tickers()

            # ── STAGE2: 15초마다 경량 갱신 (L/S·FR·OI) ───────
            if _elapsed % _STAGE2_INTERVAL == 0:
                threading.Thread(target=self._refresh_topn_scores, args=(100,), daemon=True).start()

            # ── STAGE3: 60초마다 klines 갱신 ─────────────────
            if _elapsed % _STAGE3_INTERVAL == 0:
                threading.Thread(target=self._refresh_topn_klines, args=(100,), daemon=True).start()

            # ── 카운터 리셋 (1시간 기준) + onboard_map 갱신 ──
            if _elapsed >= 3600:
                threading.Thread(target=self._fetch_onboard_map, daemon=True).start()
                _elapsed = 0

    def _refresh_topn_scores(self, n: int = 100) -> None:
        """STAGE2: 상위 N개 심볼 L/S·FR·OI 병렬 갱신 (5스레드, ~15초).
        Sharp Rise·Decline 별점·필터 정확도 및 장 단계 실데이터화.
        """
        tickers = list(self._sorted_tickers[:n])

        def _one(ticker: "SymbolTicker") -> None:
            sym      = ticker.symbol
            existing = self._ind_cache.get(sym, {})
            if existing.get("_is_detail"):
                return   # 완전 상세 데이터 있으면 스킵
            try:
                ls = self._ls_svc.fetch(sym)
                fr = self._fr_svc.fetch(sym)
                oi = self._oi_svc.fetch_change_pct(sym)
                ind = dict(existing) if existing else self._simple_ind(ticker)
                if ls:
                    ind["long_ratio"]   = ls.long_account_pct
                if fr:
                    ind["funding_rate"] = fr.funding_rate * 100.0
                ind["oi_change"] = oi
                with self._lock:
                    self._ind_cache[sym] = ind
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=_STAGE2_WORKERS) as pool:
            pool.map(_one, tickers)

    def _refresh_topn_klines(self, n: int = 100) -> None:
        """STAGE3: 상위 N개 심볼 TF klines 병렬 갱신 (7스레드, ~21초).
        TF정렬·ATR%·EMA·StochRSI·4TF별점·장 단계 실데이터화.
        갱신 TF: 1m·3m·5m·15m·1h·4h·1d (4TF거시지지 s_macro 3점 만점 정확 반영)
        """
        tickers = list(self._sorted_tickers[:n])

        def _one(ticker: "SymbolTicker") -> None:
            sym      = ticker.symbol
            existing = self._ind_cache.get(sym, {})
            if existing.get("_is_detail"):
                return   # 완전 상세 데이터 있으면 스킵
            try:
                # ── klines 수집 ──────────────────────────────
                bars: dict = {}
                for tf in _KLINES_TFS:
                    limit = 80 if tf in ("1m", "3m") else 60
                    b = self._ohlcv_svc.fetch(sym, tf, limit)
                    if b:
                        bars[tf] = b
                if not bars:
                    return

                b1h = bars.get("1h", [])
                b5m = bars.get("5m", [])

                # ── 지표 계산 ────────────────────────────────
                atr    = AtrPercent.calculate(b1h) if b1h              else 2.0
                atr_5m = AtrPercent.calculate(b5m) if len(b5m) >= 15  else 0.0
                ema = EMAAlignment.calculate(b1h) if b1h else None
                vwap_r = VWAP.calculate(b5m or b1h) if (b5m or b1h) else None
                pat  = CandlePattern.detect(b5m or b1h) if (b5m or b1h) else "분석 중 …"

                stoch:        dict[str, StochRSIResult] = {}
                stoch_series: dict[str, list[float]]   = {}
                for tf, b in bars.items():
                    stoch[tf], stoch_series[tf] = StochRSI.calculate_with_series(b)

                # ── ind 업데이트 (기존 캐시 기반) ────────────
                ind = dict(existing) if existing else self._simple_ind(ticker)

                ind["atr"]        = round(atr, 4)
                ind["atr_pct"]    = round(atr, 4)
                ind["atr_pct_5m"] = round(atr_5m, 4)
                vss = VSS.calculate(b5m or b1h) if (b5m or b1h) else 1.0
                bpr = BPR.from_candles(b1h)     if b1h           else 0.5
                ind["vss"]              = round(vss, 4)
                ind["bpr"]              = round(bpr, 4)
                ind["price_change_pct"] = round(ticker.price_change_pct, 4)
                ind["pattern"] = pat

                if ema:
                    ind["align"] = ema.align
                    ind["e5"]    = round(ema.ema5, 6)
                    ind["e10"]   = round(ema.ema10, 6)
                    ind["e20"]   = round(ema.ema20, 6)
                    ind["e50"]   = round(ema.ema50, 6)

                # volume_ratio — 1m 최근 봉 / 20봉 평균
                b1m_kr = bars.get("1m", [])
                if len(b1m_kr) >= 21:
                    avg_vol = sum(b.volume for b in b1m_kr[-20:]) / 20.0
                    ind["volume_ratio"] = round(b1m_kr[-1].volume / avg_vol, 3) if avg_vol > 0 else 1.0
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
                        }

                ind["_data_ready"] = True
                with self._lock:
                    self._ind_cache[sym] = ind
                    sym_cache = self._ohlcv_cache.setdefault(sym, {})
                    sym_cache.update(bars)

            except Exception as e:
                with self._lock:
                    self._last_refresh_error      = f"[stage3:{sym}] {e}"
                    self._last_refresh_error_time = time.time()

        with ThreadPoolExecutor(max_workers=_STAGE3_WORKERS) as pool:
            pool.map(_one, tickers)

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
        """
        if not tickers:
            return
        sorted_vol = sorted(tickers, key=lambda t: t.volume_usdt, reverse=True)
        vol_rank   = {t.symbol: i + 1 for i, t in enumerate(sorted_vol)}
        with self._lock:
            self._tickers        = tickers
            self._sorted_tickers = sorted_vol
            self._tkr_map        = {t.symbol: t for t in tickers}
            self._vol_rank       = vol_rank

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

    def _refresh_tickers(self) -> None:
        try:
            tickers = self._tkr_svc.fetch_all()
            # 거래량 내림차순 정렬 — 다른 Sort by 모드의 스코어링 풀로 사용
            sorted_vol = sorted(tickers, key=lambda t: t.volume_usdt, reverse=True)
            vol_rank = {t.symbol: i + 1 for i, t in enumerate(sorted_vol)}
            with self._lock:
                self._tickers         = tickers          # API 응답 원본 (전체)
                self._sorted_tickers  = sorted_vol       # 거래량 내림차순 (전체)
                self._tkr_map         = {t.symbol: t for t in tickers}
                self._vol_rank        = vol_rank
                self._last_tkr_refresh = time.time()
            self._rebuild_ranking_rows()
            # 5초 ticker 갱신 완료 콜백 → middle_panel 경량 랭킹 업데이트
            cb = self._on_ranking_ready_cb
            if cb is not None:
                try:
                    cb()   # → middle_panel._soft_update_ranking()
                except Exception:
                    pass
        except Exception:
            pass

    def _rebuild_ranking_rows(self) -> None:
        """Sharp Rise/Decline/Volatility/4TF 모드용 랭킹 풀 빌드.
        거래량 상위 200개 기준 — 유동성 높은 심볼 우선.
        (24h Ticker 모드는 get_all_ranked_by_change() 별도 사용)
        """
        with self._lock:
            # 거래량 정렬된 상위 200개 (기존: API 응답 순서 첫 200개 → 수정)
            tickers_snap = list(self._sorted_tickers[:200])
        rows = [self._make_row(t) for t in tickers_snap]
        with self._lock:
            self._ranking_rows = rows

    def get_all_ranked_by_change(self, limit: int = 100) -> list:
        """24h Ticker 모드 전용: 전체 심볼(628개) 변동률 내림차순 top N 반환.
        tickers[:200] 절단 없이 전체에서 가장 많이 오른 심볼 표시.
        """
        with self._lock:
            tickers_snap = list(self._tickers)   # 전체 원본 복사
        tickers_snap.sort(key=lambda t: t.price_change_pct, reverse=True)
        return [self._make_row(t) for t in tickers_snap[:limit]]

    def get_newlisted_rows(self) -> list:
        """Newly Listed 모드 전용: 전체 _tickers에서 상장 30일 이내 심볼만 행 반환.
        get_ranking_rows()의 거래량 상위 200개 제한 없이 전체 유니버스 탐색.
        """
        with self._lock:
            tickers_snap = list(self._tickers)
            onboard_snap = dict(self._onboard_map)
        result = []
        for t in tickers_snap:
            ob = onboard_snap.get(t.symbol, 0)
            if not ob:
                continue
            days = NewlistedScorer.get_days_since_listing(ob)
            if 0 < days <= 30:
                result.append(self._make_row(t))
        return result

    def _fetch_onboard_map(self) -> None:
        try:
            ei = self._client.fetch_exchange_info()
            if ei:
                m = NewlistedScorer.build_onboard_map(ei)
                with self._lock:
                    self._onboard_map = m
        except Exception:
            pass

    def _refresh_detail(self, symbol: str) -> None:
        """선택 심볼 전체 지표 갱신."""
        try:
            # OHLCV 7 TF 수집
            bars: dict[str, list[OHLCVBar]] = {}
            for tf in _DETAIL_TFS:
                n = 80 if tf in ("1m", "3m", "5m", "15m") else 60
                bars[tf] = self._ohlcv_svc.fetch(symbol, tf, n)

            # 파생 데이터
            fr  = self._fr_svc.fetch(symbol)
            oi  = self._oi_svc.fetch_change_pct(symbol)
            ls  = self._ls_svc.fetch(symbol)

            # 지표 계산 (1h 기준)
            b1h  = bars.get("1h", [])
            b5m  = bars.get("5m", [])
            rsi  = RSI.calculate(b1h)
            bpr  = BPR.from_candles(b1h)
            vss  = VSS.calculate(b5m or b1h)
            atr    = AtrPercent.calculate(b1h)
            atr_5m = AtrPercent.calculate(b5m) if len(b5m) >= 15 else 0.0
            ema  = EMAAlignment.calculate(b1h)
            vwap_r = VWAP.calculate(b5m or b1h)
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
            player_tags = [(t.tag_text, t.tag_color, t.strength_pct) for t in det.tags]

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
                player_tags=player_tags, eb=eb,
            )

            # volume_ratio — 1m 최근 봉 / 20봉 평균
            b1m_d = bars.get("1m", [])
            if len(b1m_d) >= 21:
                avg_v = sum(b.volume for b in b1m_d[-20:]) / 20.0
                ind["volume_ratio"] = round(b1m_d[-1].volume / avg_v, 3) if avg_v > 0 else 1.0
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

    # ══ dict 빌더 ═════════════════════════════════════════════

    def _build_ind_dict(
        self, symbol, tkr, bars, stoch,
        stoch_series,
        rsi, bpr, vss, atr, atr_5m, ema, vwap_r, pat,
        fr_pct, oi_chg, long_pct, liq, lev,
        player_tags, eb,
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
            "atr":        round(atr, 4),      # SYMBOL_IND에서 "atr" 키 사용
            "atr_pct":    round(atr, 4),      # 두 이름 모두 지원
            "atr_pct_5m": round(atr_5m, 4),   # 5m ATR% — SL 자동 계산용
            # EMA
            "e5":    round(ema.ema5, 6),
            "e10":   round(ema.ema10, 6),
            "e20":   round(ema.ema20, 6),
            "e50":   round(ema.ema50, 6),
            "align": ema.align,
            # VWAP
            "vwap":   vwap_r.label,
            # 캔들 패턴
            "pattern": pat,
            # 펀딩비 (% 단위, SYMBOL_IND 포맷 호환)
            "funding_rate": round(fr_pct, 4),
            # OI 변화 %
            "oi_change": round(oi_chg, 2),
            # 롱숏 비율
            "long_ratio": round(long_pct, 2),
            # 청산 근접도 (추정)
            "liq_long_pct":  round(liq.liq_long_pct, 2),
            "liq_short_pct": round(liq.liq_short_pct, 2),
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
            # Player 태그 (내부용)
            "_player_tags": player_tags,
            # STAGE2/3 경량 갱신으로부터 보호 — _process_selected() 전용 풀 상세 데이터 표시
            "_is_detail":   True,
            "_data_ready":  True,
        }

        # StochRSI TF dict 추가 (실제 교차 시점 기반 elapsed)
        cached_ind = self._ind_cache.get(symbol, {})
        for tf_key, tf_real in tf_key_map.items():
            r = stoch.get(tf_real)
            if r is None:
                d[tf_key] = {"dir": "↔", "col": _YEL, "k": 50.0, "d": 50.0,
                             "elapsed": None, "div": None,
                             "k_series": [], "d_series": []}
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
                             "k_series": ks[-40:], "d_series": ds[-40:]}

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
            "_player_tags": [],
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
            "_player_tags": [],
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

    def _make_row(self, tkr: SymbolTicker) -> tuple:
        """ticker → 실데이터 12-tuple 랭킹 행 생성."""
        sym  = tkr.symbol
        chg  = tkr.price_change_pct

        # [1] 신규 상장 days
        ob   = self._onboard_map.get(sym, 0)
        days = NewlistedScorer.get_days_since_listing(ob) if ob else 0

        # [2,3] TF 정렬 (캐시된 상세 데이터 있으면 사용)
        ind = self._ind_cache.get(sym)
        if ind:
            dirs = [ind.get(k, {}).get("dir", "↔") for k in ("tf1","tf3","tf5","tf15","tf1h","tf4h","tf1d")]
            up   = sum(1 for d in dirs if d == "▲")
            dn   = sum(1 for d in dirs if d == "▼")
            tot  = len(dirs)
            if up >= dn and up > 0:
                align_txt = f"↑  {up}/{tot}"
                align_col = _POS if up == tot else _LGR
            elif dn > up:
                align_txt = f"↓  {dn}/{tot}"
                align_col = _NEG
            else:
                align_txt = f"↔  {tot//2}/{tot}"
                align_col = _YEL
        else:
            align_txt = "↔  —"
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

        # [11] Player 태그
        player_tags = (ind or {}).get("_player_tags", [])

        return (sym, days,
                align_txt, align_col,
                chg_txt, chg_col,
                cum_txt, cum_col,
                phase_txt, phase_col,
                prio, player_tags)

