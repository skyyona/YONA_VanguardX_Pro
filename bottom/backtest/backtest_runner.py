"""
bottom/backtest/backtest_runner.py
백테스팅 실행 — 4개 시간프레임(1m/3m/5m/15m) 실제 StochRSI 합의 전략 적용.
기존 _mac_tfs bisect 패턴을 1m/3m/5m/15m에 확장 적용.
수수료(0.09%) · 슬리피지(0.02%) · 펀딩비(0.01%/8h) 거래별 PnL에 차감.
Sort by 6개 필터 + Prohibition 필터 적용.
quality_grade_req 는 QualityGrader(Cascade/Zone/Duration 3축 근사)로 반영.
"""
from __future__ import annotations

import bisect

from bottom.backtest.historical_data_loader import HistoricalDataLoader
from bottom.engine_core.quality_grader import QualityGrader
from bottom.engine_core.sort_mode_config import get_mode_config
from bottom.models import BacktestResult, BacktestTrade, StrategyParams

# 실거래 엔진과 동일한 표준 StochRSI 파라미터 (rsi_period, stoch_period, smooth_k, smooth_d)
_STOCH_P      = (14, 14, 3, 3)
# StochRSI 수렴 최소 봉 수 (rsi_p + stoch_p + sk + sd + 2 = 36 기준 + 여유)
_MIN_BARS     = 50
# K-D 최소 스프레드 (fourtf_consensus.py 동일)
_MIN_SPREAD   = 2.0
# 1m 기준 웜업 봉 수 — 신호 수렴 대기
_WARMUP_1M    = 200

# 기간별 4TF 로드 봉 수 (StochRSI 웜업 + 실 검사 구간 합산)
_TF_BARS: dict[str, dict[str, int]] = {
    "7일":  {"1m": 10320, "3m": 3450, "5m": 2100, "15m":  710},
    "14일": {"1m": 20400, "3m": 6820, "5m": 4100, "15m": 1380},
    "30일": {"1m": 43400, "3m":14500, "5m": 8700, "15m": 2920},
    "90일": {"1m":129600, "3m":43220, "5m":25960, "15m": 8680},
}

# 합의 모드 상수
_CONSENSUS_4_4 = "4/4"       # 4개 TF 모두 합의 (4/4)
_CONSENSUS_3_4 = "3/4"       # 3개 이상 TF 합의 (3/4 과반)
_CONSENSUS_A3  = "anchor3"   # 앵커 TF — 15m + 5m + 3m 3개 필수
_CONSENSUS_A2  = "anchor2"   # 앵커 TF — 15m + 5m 2개 필수

# 비용 상수 (거래별 레버리지 반영 PnL%에서 차감)
_COMMISSION   = 0.00045   # 테이커 수수료 0.045% / 편도 (Binance USDT-M)
_SLIPPAGE     = 0.00010   # 슬리피지 0.010% / 편도 (시장 충격 추정)
_FUNDING_RATE = 0.0001    # 펀딩비 0.01% / 8시간 (표준 중립 추정)
_FUNDING_BARS = 480       # 8시간 = 480개 1m봉

# EMA / ATR / 거래량 계산 윈도우
_EMA_SHORT  = 5
_EMA_LONG   = 50
_ATR_PERIOD = 14
_VOL_PERIOD = 20

# Prohibition 임계값
_ATR_BAN      = 8.0
_NEW_DAYS_BAN = 14
# quality_grade_req 등급 서열 — A(0) 가장 엄격, D(3) 최완화
_GRADE_ORDER  = {"A": 0, "B": 1, "C": 2, "D": 3}
# common_macro HTF StochRSI 파라미터 (실거래 엔진 동일)
_MAC_KD_PARAMS = (14, 14, 3, 3)


def _fmt_elapsed(minutes: float) -> str | None:
    """경과 분(minutes)을 한국어 경과 문자열로 변환. 음수면 None 반환."""
    if minutes < 0:
        return None
    if minutes < 1:
        return "방금"
    if minutes < 60:
        return f"{int(minutes)}분 전"
    return f"{int(minutes // 60)}시간 전"


def _grade_ok(computed: str, required: str | None) -> bool:
    """computed 등급이 required 이상(더 엄격하거나 같음)인지 확인."""
    if required is None:
        return True
    return _GRADE_ORDER.get(computed, 3) <= _GRADE_ORDER.get(required, 3)


class BacktestRunner:
    """4TF 실제 시간프레임 StochRSI 합의 전략 과거 데이터 백테스팅.

    1m/3m/5m/15m 봉을 별도 로드하고 bisect 시점 매핑으로 각 스캔 시점의
    K/D 값을 조회한다. 수수료·슬리피지·펀딩비를 거래별 PnL%에 차감한다.
    Phase1(초기SL) → Phase2(BEP이동) → Phase3(트레일링스탑) 청산 시뮬레이션.
    """

    @classmethod
    def load_tf_bars(cls, symbol: str, period: str = "7일") -> dict:
        """4개 TF 봉 데이터를 1회 로드 — run_comparison에서 API 4배 호출 방지."""
        bars_cfg = _TF_BARS.get(period, _TF_BARS["7일"])
        return {
            "1m":  HistoricalDataLoader.load_bars(symbol, "1m",  bars_cfg["1m"]),
            "3m":  HistoricalDataLoader.load_bars(symbol, "3m",  bars_cfg["3m"]),
            "5m":  HistoricalDataLoader.load_bars(symbol, "5m",  bars_cfg["5m"]),
            "15m": HistoricalDataLoader.load_bars(symbol, "15m", bars_cfg["15m"]),
        }

    @classmethod
    def run(cls, symbol: str, params: StrategyParams, period: str = "7일",
            consensus_mode: str = _CONSENSUS_4_4,
            preloaded: "dict | None" = None) -> BacktestResult:
        period_days = cls._days(period)
        bars_cfg    = _TF_BARS.get(period, _TF_BARS["7일"])

        # ── 4개 TF 봉 로드 (preloaded 제공 시 API 호출 생략) ──────
        if preloaded is not None:
            bars_1m  = preloaded["1m"]
            bars_3m  = preloaded["3m"]
            bars_5m  = preloaded["5m"]
            bars_15m = preloaded["15m"]
        else:
            bars_1m  = HistoricalDataLoader.load_bars(symbol, "1m",  bars_cfg["1m"])
            bars_3m  = HistoricalDataLoader.load_bars(symbol, "3m",  bars_cfg["3m"])
            bars_5m  = HistoricalDataLoader.load_bars(symbol, "5m",  bars_cfg["5m"])
            bars_15m = HistoricalDataLoader.load_bars(symbol, "15m", bars_cfg["15m"])

        if len(bars_1m) < _MIN_BARS or not bars_3m or not bars_5m or not bars_15m:
            return BacktestResult(symbol=symbol, sort_mode=params.sort_mode,
                                  period_days=period_days)

        # ── 각 TF StochRSI K/D 시리즈 사전 계산 ───────────────────
        def _make_tf(bars_list: list) -> "tuple | None":
            ks, ds = cls._calc_kd([b.close for b in bars_list], *_STOCH_P)
            if not ks:
                return None
            offset = len(bars_list) - len(ks)
            return ([b.open_time for b in bars_list], offset, ks, ds)

        tf_data = {
            "1m":  _make_tf(bars_1m),
            "3m":  _make_tf(bars_3m),
            "5m":  _make_tf(bars_5m),
            "15m": _make_tf(bars_15m),
        }
        if any(v is None for v in tf_data.values()):
            return BacktestResult(symbol=symbol, sort_mode=params.sort_mode,
                                  period_days=period_days)

        # ── Sort by 필터 사전 계산 (5m 기준 — 실거래 엔진과 동일) ──
        cfg = get_mode_config(params.sort_mode)

        atr_pct_5m = cls._calc_atr_series(bars_5m, _ATR_PERIOD)
        times_5m   = [b.open_time for b in bars_5m]

        vol_ratio_5m: list[float] = []
        if cfg.volume_mult is not None:
            vol_ratio_5m = cls._calc_vol_ratio_series(bars_5m, _VOL_PERIOD)

        ema5_5m:  list[float] = []
        ema50_5m: list[float] = []
        if cfg.macro_ema:
            closes_5m = [b.close for b in bars_5m]
            ema5_5m   = cls._calc_ema_series(closes_5m, _EMA_SHORT)
            ema50_5m  = cls._calc_ema_series(closes_5m, _EMA_LONG)

        # ── common_new 상장 일수 ─────────────────────────────────
        _days_listed = 9999
        if params.prohibition.common_new:
            _dlisted     = HistoricalDataLoader.load(symbol, "1d", _NEW_DAYS_BAN + 5)
            _days_listed = len(_dlisted)

        # ── common_macro·use_macro HTF StochRSI (기존 bisect 패턴 유지) ─
        _mac_tfs: list = []
        if params.prohibition.common_macro or params.use_macro:
            _mac_limits = (
                ("1h", min(period_days * 25 + 50, 1500)),
                ("4h", min(period_days *  7 + 50, 1500)),
                ("1d", min(period_days      + 50,  500)),
            )
            for _tf_iv, _tf_lim in _mac_limits:
                _tf_bars = HistoricalDataLoader.load(symbol, _tf_iv, _tf_lim)
                if len(_tf_bars) >= 36:
                    _tf_k, _tf_d = cls._calc_kd(
                        [b.close for b in _tf_bars], *_MAC_KD_PARAMS)
                    if _tf_k:
                        _mac_tfs.append((
                            [b.open_time for b in _tf_bars],
                            len(_tf_bars) - len(_tf_k),
                            _tf_k,
                            _tf_d,
                        ))

        # ── 메인 루프 (1m 봉 기준 스캔, 웜업 이후부터) ──────────────
        trades:     list[BacktestTrade] = []
        _tf_min   = 4 if params.prohibition.common_4tf else 3

        in_long     = False
        in_short    = False
        entry_price = 0.0
        entry_time  = 0
        entry_bar_i = 0   # 펀딩비 계산용 진입 봉 인덱스
        phase       = 1
        trail_ref   = 0.0

        n_1m = len(bars_1m)
        # tf5 교차 시점 추적 — QualityGrader _duration_score 재현용
        _tf5_long_cross_t:  float = 0.0   # tf5 K>D 교차 발생 시점 (ms)
        _tf5_short_cross_t: float = 0.0   # tf5 K<D 교차 발생 시점 (ms)
        _prev_tf5_long_ok:  bool  = False
        _prev_tf5_short_ok: bool  = False
        for i in range(_WARMUP_1M, n_1m):
            bar   = bars_1m[i]
            close = bar.close
            t     = bar.open_time

            # ── 5m 기준 필터 값 bisect 조회 ──────────────────────
            pos_5m  = max(0, bisect.bisect_left(times_5m, t) - 1)
            atr_pct = atr_pct_5m[pos_5m] if pos_5m < len(atr_pct_5m) else 0.0
            atr_ok  = cfg.atr_min <= atr_pct <= cfg.atr_max
            if params.prohibition.common_atr and atr_pct > _ATR_BAN:
                atr_ok = False

            vol_ok = True
            if cfg.volume_mult is not None and vol_ratio_5m:
                vr     = vol_ratio_5m[pos_5m] if pos_5m < len(vol_ratio_5m) else 1.0
                vol_ok = vr >= cfg.volume_mult

            # ── 롱 포지션 관리 ────────────────────────────────────
            if in_long:
                bars_held = i - entry_bar_i
                R         = entry_price * params.stop_loss / 100.0
                sl_phase1 = entry_price * (1.0 - params.stop_loss / 100.0)

                if phase == 1:
                    if close <= sl_phase1:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (close - entry_price) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="SL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    if close >= entry_price + R:
                        phase = 2; trail_ref = close

                elif phase == 2:
                    if close <= entry_price:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (close - entry_price) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="BEP-SL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    if close >= entry_price + R * 1.5:
                        phase = 3; trail_ref = close

                elif phase == 3:
                    trail_ref = max(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 - params.trail_stop / 100.0)
                    if close <= trail_sl:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (close - entry_price) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="TRAIL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 숏 포지션 관리 ────────────────────────────────────
            elif in_short:
                bars_held = i - entry_bar_i
                R         = entry_price * params.stop_loss / 100.0
                sl_phase1 = entry_price * (1.0 + params.stop_loss / 100.0)

                if phase == 1:
                    if close >= sl_phase1:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (entry_price - close) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="SL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    if close <= entry_price - R:
                        phase = 2; trail_ref = close

                elif phase == 2:
                    if close >= entry_price:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (entry_price - close) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="BEP-SL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    if close <= entry_price - R * 1.5:
                        phase = 3; trail_ref = close

                elif phase == 3:
                    trail_ref = min(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 + params.trail_stop / 100.0)
                    if close >= trail_sl:
                        cost = cls._cost(params.leverage, bars_held)
                        pnl  = (entry_price - close) / entry_price * 100.0 * params.leverage - cost
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="TRAIL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 신규 진입 (포지션 없을 때만) ─────────────────────
            if not in_long and not in_short:
                # 4TF StochRSI 방향 산출 (bisect 시점 매핑)
                long_v  = 0
                short_v = 0
                tf_dirs: dict[str, int] = {}
                k_5m    = 50.0   # G2 임계값용 5m K값
                tf_kd:  dict[str, tuple] = {}  # quality_grade_req 용 전 TF K/D

                for tf_key, (tf_times, tf_off, tf_k, tf_d) in tf_data.items():
                    pos_tf = bisect.bisect_left(tf_times, t) - 1
                    idx    = pos_tf - tf_off
                    if 0 <= idx < len(tf_k):
                        k, d   = tf_k[idx], tf_d[idx]
                        tf_kd[tf_key] = (k, d)
                        spread = abs(k - d)
                        if k > d and spread >= _MIN_SPREAD:
                            long_v         += 1
                            tf_dirs[tf_key] = 1
                        elif k < d and spread >= _MIN_SPREAD:
                            short_v        += 1
                            tf_dirs[tf_key] = -1
                        else:
                            tf_dirs[tf_key] = 0
                        if tf_key == "5m":
                            k_5m = k
                    else:
                        tf_dirs[tf_key] = 0

                # tf5 교차 추적 (QualityGrader _duration_score elapsed용)
                _c5k, _c5d = tf_kd.get("5m", (50.0, 50.0))
                _lo5 = _c5k > _c5d and abs(_c5k - _c5d) >= _MIN_SPREAD
                _so5 = _c5k < _c5d and abs(_c5k - _c5d) >= _MIN_SPREAD
                if _lo5 and not _prev_tf5_long_ok:
                    _tf5_long_cross_t  = t
                if _so5 and not _prev_tf5_short_ok:
                    _tf5_short_cross_t = t
                _prev_tf5_long_ok  = _lo5
                _prev_tf5_short_ok = _so5

                # G1: 합의 모드별 진입 가능 여부
                can_long, can_short = cls._check_consensus(
                    consensus_mode, long_v, short_v, tf_dirs, _tf_min)

                # G8: common_macro / use_macro 거시 추세 체크
                _mac_ok_long = _mac_ok_short = True
                if _mac_tfs:
                    _mac_score = 0
                    for _tf_times, _tf_off, _tf_k, _tf_d in _mac_tfs:
                        _pos = bisect.bisect_left(_tf_times, t) - 1
                        _idx = _pos - _tf_off
                        if 0 <= _idx < len(_tf_k):
                            _k = _tf_k[_idx]
                            _d = _tf_d[_idx]
                            if _k > _d and abs(_k - _d) >= 2.0:
                                _mac_score += 1
                            elif _k < _d and abs(_k - _d) >= 2.0:
                                _mac_score -= 1
                    _mac_ok_long  = (_mac_score > -1)
                    _mac_ok_short = (_mac_score <  1)

                # ── 롱 진입 시도 ──────────────────────────────────
                if (can_long
                        and k_5m < cfg.k_long_max
                        and cfg.direction_bias != "short_only"
                        and atr_ok and vol_ok
                        and not (params.prohibition.common_new and _days_listed < _NEW_DAYS_BAN)
                        and _mac_ok_long):
                    ema_ok = True
                    if cfg.macro_ema and ema50_5m and pos_5m >= _EMA_LONG:
                        e50    = ema50_5m[pos_5m]
                        ema_ok = (ema5_5m[pos_5m] > e50) if e50 > 0 else True
                    swing_ok = True
                    if cfg.requires_swing:
                        swing_ok = cls._swing_bull(bars_1m, i)

                    if ema_ok and swing_ok:
                        grade_ok = True
                        if cfg.quality_grade_req is not None:
                            _em_l = (t - _tf5_long_cross_t) / 60_000 if _tf5_long_cross_t > 0 else -1
                            _el_l = _fmt_elapsed(_em_l)
                            _ind_l = {
                                "tf1":  {"k": tf_kd.get("1m",  (50.0, 50.0))[0], "d": tf_kd.get("1m",  (50.0, 50.0))[1]},
                                "tf3":  {"k": tf_kd.get("3m",  (50.0, 50.0))[0], "d": tf_kd.get("3m",  (50.0, 50.0))[1]},
                                "tf5":  {"k": tf_kd.get("5m",  (50.0, 50.0))[0], "d": tf_kd.get("5m",  (50.0, 50.0))[1], "elapsed": _el_l},
                                "tf15": {"k": tf_kd.get("15m", (50.0, 50.0))[0], "d": tf_kd.get("15m", (50.0, 50.0))[1]},
                            }
                            _grd_l, _ = QualityGrader.grade(_ind_l, "long")
                            grade_ok = _grade_ok(_grd_l, cfg.quality_grade_req)
                        if grade_ok:
                            in_long     = True
                            entry_price = close
                            entry_time  = bar.open_time
                            entry_bar_i = i
                            phase       = 1
                            trail_ref   = close

                # ── 숏 진입 시도 ──────────────────────────────────
                elif (can_short
                        and k_5m > cfg.k_short_min
                        and cfg.direction_bias != "long_only"
                        and atr_ok and vol_ok
                        and not (params.prohibition.common_new and _days_listed < _NEW_DAYS_BAN)
                        and _mac_ok_short):
                    ema_ok = True
                    if cfg.macro_ema and ema50_5m and pos_5m >= _EMA_LONG:
                        e50    = ema50_5m[pos_5m]
                        ema_ok = (ema5_5m[pos_5m] < e50) if e50 > 0 else True
                    swing_ok = True
                    if cfg.requires_swing:
                        swing_ok = cls._swing_bear(bars_1m, i)

                    if ema_ok and swing_ok:
                        grade_ok = True
                        if cfg.quality_grade_req is not None:
                            _em_s = (t - _tf5_short_cross_t) / 60_000 if _tf5_short_cross_t > 0 else -1
                            _el_s = _fmt_elapsed(_em_s)
                            _ind_s = {
                                "tf1":  {"k": tf_kd.get("1m",  (50.0, 50.0))[0], "d": tf_kd.get("1m",  (50.0, 50.0))[1]},
                                "tf3":  {"k": tf_kd.get("3m",  (50.0, 50.0))[0], "d": tf_kd.get("3m",  (50.0, 50.0))[1]},
                                "tf5":  {"k": tf_kd.get("5m",  (50.0, 50.0))[0], "d": tf_kd.get("5m",  (50.0, 50.0))[1], "elapsed": _el_s},
                                "tf15": {"k": tf_kd.get("15m", (50.0, 50.0))[0], "d": tf_kd.get("15m", (50.0, 50.0))[1]},
                            }
                            _grd_s, _ = QualityGrader.grade(_ind_s, "short")
                            grade_ok = _grade_ok(_grd_s, cfg.quality_grade_req)
                        if grade_ok:
                            in_short    = True
                            entry_price = close
                            entry_time  = bar.open_time
                            entry_bar_i = i
                            phase       = 1
                            trail_ref   = close

        from bottom.backtest.result_summary import ResultSummary
        return ResultSummary.build(symbol, params.sort_mode, period_days, trades)

    @classmethod
    def run_comparison(
        cls,
        symbol: str,
        params: StrategyParams,
        period: str = "7일",
    ) -> "dict[str, BacktestResult]":
        """4가지 합의 모드 동시 비교 실행 — 봉 데이터 1회 로드 후 4모드 공유.

        Returns
        -------
        dict: 모드별 BacktestResult
            키: '4/4', '3/4', 'anchor3', 'anchor2'
        """
        preloaded = cls.load_tf_bars(symbol, period)
        results: dict[str, BacktestResult] = {}
        for mode in (_CONSENSUS_A2, _CONSENSUS_A3, _CONSENSUS_3_4, _CONSENSUS_4_4):
            results[mode] = cls.run(symbol, params, period,
                                    consensus_mode=mode, preloaded=preloaded)
        return results

    # ── 거래 비용 계산 ──────────────────────────────────────────
    @staticmethod
    def _cost(leverage: int, bars_held: int) -> float:
        """레버리지 반영 거래 비용 (수수료 + 슬리피지 + 펀딩비) — PnL%에서 차감할 값."""
        round_trip = 2 * leverage * (_COMMISSION + _SLIPPAGE)
        funding    = leverage * _FUNDING_RATE * (bars_held / _FUNDING_BARS)
        return round_trip + funding

    # ── 합의 모드 판정 ───────────────────────────────────────────
    @staticmethod
    def _check_consensus(mode: str, long_v: int, short_v: int,
                         tf_dirs: dict, tf_min: int) -> "tuple[bool, bool]":
        """합의 모드별 롱/숏 진입 가능 여부 반환."""
        if mode == _CONSENSUS_4_4:
            return long_v >= 4, short_v >= 4
        if mode == _CONSENSUS_3_4:
            return long_v >= tf_min, short_v >= tf_min
        if mode == _CONSENSUS_A3:   # 15m + 5m + 3m 앵커
            can_long  = (tf_dirs.get("15m") == 1
                         and tf_dirs.get("5m") == 1
                         and tf_dirs.get("3m") == 1)
            can_short = (tf_dirs.get("15m") == -1
                         and tf_dirs.get("5m") == -1
                         and tf_dirs.get("3m") == -1)
            return can_long, can_short
        if mode == _CONSENSUS_A2:   # 15m + 5m 앵커
            can_long  = tf_dirs.get("15m") == 1  and tf_dirs.get("5m") == 1
            can_short = tf_dirs.get("15m") == -1 and tf_dirs.get("5m") == -1
            return can_long, can_short
        return False, False

    # ── ATR% 시리즈 계산 ─────────────────────────────────────────

    @staticmethod
    def _calc_atr_series(bars: list, period: int = 14) -> list[float]:
        """전체 봉 ATR% 시리즈 사전 계산 (True Range 기반)."""
        n = len(bars)
        result = [0.0] * n
        if n < 2:
            return result
        tr_list = [0.0] * n
        for k in range(1, n):
            h  = bars[k].high
            l  = bars[k].low
            pc = bars[k - 1].close
            tr_list[k] = max(h - l, abs(h - pc), abs(l - pc))
        for k in range(1, n):
            start  = max(1, k - period + 1)
            count  = k - start + 1
            avg_tr = sum(tr_list[start: k + 1]) / count
            result[k] = (avg_tr / bars[k].close * 100.0
                         if bars[k].close > 0 else 0.0)
        return result

    # ── 거래량 배수 시리즈 계산 ──────────────────────────────────

    @staticmethod
    def _calc_vol_ratio_series(bars: list, period: int = 20) -> list[float]:
        """현재봉 거래량 / 직전 N봉 평균 거래량 시리즈 사전 계산."""
        n = len(bars)
        result = [1.0] * n
        for k in range(period, n):
            avg_v     = sum(bars[j].volume for j in range(k - period, k)) / period
            result[k] = bars[k].volume / avg_v if avg_v > 0 else 1.0
        return result

    # ── EMA 시리즈 계산 ──────────────────────────────────────────

    @staticmethod
    def _calc_ema_series(closes: list[float], period: int) -> list[float]:
        """전체 close EMA 시리즈 사전 계산 (SMA 시드 방식)."""
        n = len(closes)
        if n < period:
            return list(closes)
        result = [0.0] * n
        result[period - 1] = sum(closes[:period]) / period
        k = 2.0 / (period + 1)
        for i in range(period, n):
            result[i] = closes[i] * k + result[i - 1] * (1.0 - k)
        for i in range(period - 1):
            result[i] = closes[i]
        return result

    # ── 스윙 구조 판단 ────────────────────────────────────────────

    @staticmethod
    def _swing_bull(bars: list, idx: int) -> bool:
        """상승 스윙 구조 (직전 6봉): 고점·저점 교대 상승."""
        if idx < 5:
            return False
        h = [bars[idx - (5 - k)].high for k in range(6)]
        l = [bars[idx - (5 - k)].low  for k in range(6)]
        return (h[5] > h[3] > h[1]) and (l[5] > l[3] > l[1])

    @staticmethod
    def _swing_bear(bars: list, idx: int) -> bool:
        """하락 스윙 구조 (직전 6봉): 고점·저점 교대 하락."""
        if idx < 5:
            return False
        h = [bars[idx - (5 - k)].high for k in range(6)]
        l = [bars[idx - (5 - k)].low  for k in range(6)]
        return (h[5] < h[3] < h[1]) and (l[5] < l[3] < l[1])

    # ── StochRSI K·D 시리즈 계산 ─────────────────────────────────

    @staticmethod
    def _calc_kd(closes: list[float], rsi_p: int, stoch_p: int,
                 sk: int, sd: int) -> tuple[list[float], list[float]]:
        """주어진 파라미터로 StochRSI K·D 전체 시리즈 계산.

        mtf_stochrsi.py 의 _rsi_series()/_sma() 와 동일 알고리즘.
        반환: (k_series, d_series) — 동일 길이, 시간 오름차순.
        """
        n = len(closes)
        if n < rsi_p + stoch_p + sk + sd + 2:
            return [], []

        # ① RSI 시리즈 (Wilder smoothing)
        gains  = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
        avg_g  = sum(gains[:rsi_p])  / rsi_p
        avg_l  = sum(losses[:rsi_p]) / rsi_p
        rsi_ser: list[float] = []
        for i in range(rsi_p, len(gains)):
            avg_g = (avg_g * (rsi_p - 1) + gains[i])  / rsi_p
            avg_l = (avg_l * (rsi_p - 1) + losses[i]) / rsi_p
            rs = avg_g / avg_l if avg_l > 0 else 100.0
            rsi_ser.append(100.0 - 100.0 / (1.0 + rs))

        # ② 스토캐스틱 시리즈
        stoch_ser: list[float] = []
        for i in range(stoch_p - 1, len(rsi_ser)):
            win = rsi_ser[i - stoch_p + 1: i + 1]
            lo, hi = min(win), max(win)
            stoch_ser.append((rsi_ser[i] - lo) / (hi - lo) * 100.0 if hi > lo else 50.0)

        if len(stoch_ser) < sk + sd:
            return [], []

        # ③ K = SMA(stoch, sk)
        k_ser = [sum(stoch_ser[i - sk + 1: i + 1]) / sk
                 for i in range(sk - 1, len(stoch_ser))]

        if len(k_ser) < sd:
            return [], []

        # ④ D = SMA(K, sd)
        d_ser = [sum(k_ser[i - sd + 1: i + 1]) / sd
                 for i in range(sd - 1, len(k_ser))]

        trim = len(d_ser)
        return k_ser[-trim:], d_ser

    @staticmethod
    def _days(period: str) -> int:
        return {"7일": 7, "14일": 14, "30일": 30, "90일": 90}.get(period, 7)
