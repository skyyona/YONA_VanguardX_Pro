"""
bottom/backtest/backtest_runner.py
백테스팅 실행 — 과거 데이터에 4TF 다속도 StochRSI 합의 전략 적용
Sort by 6개 필터 + Prohibition 4개 필터(common_4tf / common_atr / common_macro·use_macro / common_new) 적용
quality_grade_req 는 단일 TF 과거데이터 백테스팅 특성상 제외됨 (결과 안내에 표시)
"""
from __future__ import annotations

import bisect

from bottom.backtest.historical_data_loader import HistoricalDataLoader
from bottom.engine_core.sort_mode_config import get_mode_config
from bottom.models import BacktestResult, BacktestTrade, StrategyParams

# 4가지 StochRSI 속도 파라미터 (rsi_period, stoch_period, smooth_k, smooth_d)
_STOCH_PARAMS = [
    ( 7,  7, 3, 3),   # 단기 — 1m TF 유사
    (14, 14, 3, 3),   # 표준 — 실제 엔진 동일
    (21, 21, 3, 3),   # 중기 — 1h TF 유사
    (28, 28, 3, 3),   # 장기 — 4h TF 유사
]

# 가장 느린 파라미터(28,28,3,3) 기준 최소 필요 봉 수
_MIN_BARS   = 65
# 실제 엔진과 동일한 K/D 최소 스프레드
_MIN_SPREAD = 2.0
# EMA 계산 윈도우
_EMA_SHORT  = 5
_EMA_LONG   = 50
# ATR 계산 윈도우
_ATR_PERIOD = 14
# 거래량 비교 윈도우
_VOL_PERIOD = 20
# 절대 거래 금지 임계값 (prohibition_filter.py 동일 기준)
_ATR_BAN       = 8.0            # common_atr 과변동 금지 기준
_NEW_DAYS_BAN  = 14             # common_new 신규 상장 금지 기준
_MAC_KD_PARAMS = (14, 14, 3, 3) # common_macro HTF StochRSI 표준 파라미터


class BacktestRunner:
    """4TF 다속도 StochRSI 합의 전략 과거 데이터 백테스팅.

    동일 과거 데이터에 4가지 속도 파라미터(rsi=7/14/21/28)로 StochRSI를
    계산하여 3/4 이상 합의 + Sort by 6개 필터(direction_bias / K임계값 / ATR / 거래량 /
    EMA거시 / 스윙) + Prohibition 4개 필터(common_4tf / common_atr /
    common_macro·use_macro / common_new) 충족 시 진입.
    Phase1(초기SL) → Phase2(BEP이동) → Phase3(트레일링스탑) 청산 시뮬레이션.
    """

    @classmethod
    def run(cls, symbol: str, params: StrategyParams, period: str = "7일") -> BacktestResult:
        bars = HistoricalDataLoader.load_for_period(symbol, period)
        period_days = cls._days(period)

        if len(bars) < _MIN_BARS:
            return BacktestResult(symbol=symbol, sort_mode=params.sort_mode,
                                  period_days=period_days)

        cfg    = get_mode_config(params.sort_mode)
        closes = [b.close for b in bars]

        # ── 사전 계산: 4가지 속도 StochRSI K/D 시리즈 ──────────────
        kd_list: list[tuple[list[float], list[float]]] = []
        for rsi_p, stoch_p, sk, sd in _STOCH_PARAMS:
            k_ser, d_ser = cls._calc_kd(closes, rsi_p, stoch_p, sk, sd)
            kd_list.append((k_ser, d_ser))

        # 모든 시리즈 공통 최소 길이 (가장 느린 파라미터가 가장 짧은 시리즈 생성)
        min_len = min(len(ks) for ks, _ in kd_list)
        if min_len < 5:
            return BacktestResult(symbol=symbol, sort_mode=params.sort_mode,
                                  period_days=period_days)

        # bars 인덱스 오프셋 — kd_list[*][i] 와 bars[bar_offset + i] 가 같은 봉
        bar_offset = len(bars) - min_len

        # ── 사전 계산: ATR% / 거래량배수 / EMA 시리즈 ───────────────
        atr_pct_ser = cls._calc_atr_series(bars, _ATR_PERIOD)

        vol_ratio_ser: list[float] = []
        if cfg.volume_mult is not None:
            vol_ratio_ser = cls._calc_vol_ratio_series(bars, _VOL_PERIOD)

        ema5_ser:  list[float] = []
        ema50_ser: list[float] = []
        if cfg.macro_ema:
            ema5_ser  = cls._calc_ema_series(closes, _EMA_SHORT)
            ema50_ser = cls._calc_ema_series(closes, _EMA_LONG)

        # ── 사전 계산: common_new 상장 일수 ─────────────────────────
        _days_listed = 9999
        if params.prohibition.common_new:
            _dlisted     = HistoricalDataLoader.load(symbol, "1d", _NEW_DAYS_BAN + 5)
            _days_listed = len(_dlisted)

        # ── 사전 계산: common_macro HTF StochRSI ────────────────────
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
                        [b.close for b in _tf_bars], *_MAC_KD_PARAMS
                    )
                    if _tf_k:
                        _mac_tfs.append((
                            [b.open_time for b in _tf_bars],
                            len(_tf_bars) - len(_tf_k),
                            _tf_k,
                            _tf_d,
                        ))

        # ── 메인 루프 ─────────────────────────────────────────────────
        trades: list[BacktestTrade] = []
        _tf_min = 4 if params.prohibition.common_4tf else 3

        in_long     = False
        in_short    = False
        entry_price = 0.0
        entry_time  = 0
        phase       = 1      # 1=초기SL단계, 2=BEP이동됨, 3=트레일링
        trail_ref   = 0.0    # 롱: 기준 최고가 / 숏: 기준 최저가

        for i in range(1, min_len):
            bar_idx = bar_offset + i
            bar     = bars[bar_idx]
            close   = bar.close

            # ── 롱 포지션 관리 ────────────────────────────────────────
            if in_long:
                R         = entry_price * params.stop_loss / 100.0
                sl_phase1 = entry_price * (1.0 - params.stop_loss / 100.0)

                if phase == 1:
                    if close <= sl_phase1:
                        pnl = (close - entry_price) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="SL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    if close >= entry_price + R:        # +1R → BEP 이동
                        phase = 2
                        trail_ref = close

                elif phase == 2:
                    if close <= entry_price:            # BEP SL 도달
                        pnl = (close - entry_price) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="BEP-SL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    if close >= entry_price + R * 1.5:  # +1.5R → 트레일링 전환
                        phase = 3
                        trail_ref = close

                elif phase == 3:
                    trail_ref = max(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 - params.trail_stop / 100.0)
                    if close <= trail_sl:
                        pnl = (close - entry_price) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="TRAIL",
                        ))
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 숏 포지션 관리 ────────────────────────────────────────
            elif in_short:
                R         = entry_price * params.stop_loss / 100.0
                sl_phase1 = entry_price * (1.0 + params.stop_loss / 100.0)

                if phase == 1:
                    if close >= sl_phase1:
                        pnl = (entry_price - close) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="SL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    if close <= entry_price - R:        # +1R → BEP 이동
                        phase = 2
                        trail_ref = close

                elif phase == 2:
                    if close >= entry_price:            # BEP SL 도달
                        pnl = (entry_price - close) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="BEP-SL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    if close <= entry_price - R * 1.5:  # +1.5R → 트레일링 전환
                        phase = 3
                        trail_ref = close

                elif phase == 3:
                    trail_ref = min(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 + params.trail_stop / 100.0)
                    if close >= trail_sl:
                        pnl = (entry_price - close) / entry_price * 100.0 * params.leverage
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=round(pnl * entry_price / 100.0, 4),
                            exit_reason="TRAIL",
                        ))
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 신규 진입 (포지션 없을 때만) ─────────────────────────
            if not in_long and not in_short:
                long_v = short_v = 0
                k_std  = 50.0   # 표준 파라미터(#2, 14/14/3/3)의 K값
                for j, (ks, ds) in enumerate(kd_list):
                    k_now  = ks[i]
                    d_now  = ds[i]
                    spread = abs(k_now - d_now)
                    if k_now > d_now and spread >= _MIN_SPREAD:
                        long_v  += 1
                    elif k_now < d_now and spread >= _MIN_SPREAD:
                        short_v += 1
                    if j == 1:    # 표준 파라미터(#2, 14/14/3/3)
                        k_std = k_now

                # G4: ATR% 범위 (항상 적용)
                atr_pct = atr_pct_ser[bar_idx] if bar_idx < len(atr_pct_ser) else 0.0
                atr_ok  = cfg.atr_min <= atr_pct <= cfg.atr_max

                # G5: 거래량 배수 (volume_mult 설정 시만 적용)
                vol_ok = True
                if cfg.volume_mult is not None and vol_ratio_ser:
                    vr     = vol_ratio_ser[bar_idx] if bar_idx < len(vol_ratio_ser) else 1.0
                    vol_ok = vr >= cfg.volume_mult

                # G8-a: common_atr 과변동 절대 금지
                if params.prohibition.common_atr and atr_pct > _ATR_BAN:
                    atr_ok = False

                # G8-b: common_macro 거시 추세 방향 체크
                _mac_ok_long = _mac_ok_short = True
                if _mac_tfs:
                    _mac_score = 0
                    for _tf_times, _tf_off, _tf_k, _tf_d in _mac_tfs:
                        _pos = bisect.bisect_left(_tf_times, bar.open_time) - 1
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

                # ── 롱 진입 시도 ──────────────────────────────────────
                if (long_v >= _tf_min
                        and k_std < cfg.k_long_max
                        and cfg.direction_bias != "short_only"
                        and atr_ok
                        and vol_ok
                        and not (params.prohibition.common_new and _days_listed < _NEW_DAYS_BAN)
                        and _mac_ok_long):
                    # G6: EMA 거시 (롱: EMA5 > EMA50)
                    ema_ok = True
                    if cfg.macro_ema and ema50_ser and bar_idx >= _EMA_LONG:
                        e5  = ema5_ser[bar_idx]
                        e50 = ema50_ser[bar_idx]
                        ema_ok = (e5 > e50) if e50 > 0 else True
                    # G7: 스윙 구조 (롱: 상승 스윙)
                    swing_ok = True
                    if cfg.requires_swing:
                        swing_ok = cls._swing_bull(bars, bar_idx)

                    if ema_ok and swing_ok:
                        in_long     = True
                        entry_price = close
                        entry_time  = bar.open_time
                        phase       = 1
                        trail_ref   = close

                # ── 숏 진입 시도 ──────────────────────────────────────
                elif (short_v >= _tf_min
                        and k_std > cfg.k_short_min
                        and cfg.direction_bias != "long_only"
                        and atr_ok
                        and vol_ok
                        and not (params.prohibition.common_new and _days_listed < _NEW_DAYS_BAN)
                        and _mac_ok_short):
                    # G6: EMA 거시 (숏: EMA5 < EMA50)
                    ema_ok = True
                    if cfg.macro_ema and ema50_ser and bar_idx >= _EMA_LONG:
                        e5  = ema5_ser[bar_idx]
                        e50 = ema50_ser[bar_idx]
                        ema_ok = (e5 < e50) if e50 > 0 else True
                    # G7: 스윙 구조 (숏: 하락 스윙)
                    swing_ok = True
                    if cfg.requires_swing:
                        swing_ok = cls._swing_bear(bars, bar_idx)

                    if ema_ok and swing_ok:
                        in_short    = True
                        entry_price = close
                        entry_time  = bar.open_time
                        phase       = 1
                        trail_ref   = close

        from bottom.backtest.result_summary import ResultSummary
        return ResultSummary.build(symbol, params.sort_mode, period_days, trades)

    # ── ATR% 시리즈 계산 ─────────────────────────────────────────────

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

    # ── 거래량 배수 시리즈 계산 ──────────────────────────────────────

    @staticmethod
    def _calc_vol_ratio_series(bars: list, period: int = 20) -> list[float]:
        """현재봉 거래량 / 직전 N봉 평균 거래량 시리즈 사전 계산."""
        n = len(bars)
        result = [1.0] * n
        for k in range(period, n):
            avg_v     = sum(bars[j].volume for j in range(k - period, k)) / period
            result[k] = bars[k].volume / avg_v if avg_v > 0 else 1.0
        return result

    # ── EMA 시리즈 계산 ──────────────────────────────────────────────

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
        # period 미만 구간: close 값으로 채움 (bar_idx >= _EMA_LONG 가드로 실제 미사용)
        for i in range(period - 1):
            result[i] = closes[i]
        return result

    # ── 스윙 구조 판단 ────────────────────────────────────────────────

    @staticmethod
    def _swing_bull(bars: list, idx: int) -> bool:
        """상승 스윙 구조 (직전 6봉): 고점·저점 교대 상승."""
        if idx < 5:
            return False
        # h[0]=가장오래전봉, h[5]=현재봉
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

    # ── StochRSI K·D 시리즈 계산 ─────────────────────────────────────

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

        # K와 D 길이 정렬 (D가 항상 K보다 sd-1 만큼 짧음 → K 앞쪽 제거)
        trim = len(d_ser)
        return k_ser[-trim:], d_ser

    @staticmethod
    def _days(period: str) -> int:
        return {"7일": 7, "14일": 14, "30일": 30, "90일": 90}.get(period, 7)
