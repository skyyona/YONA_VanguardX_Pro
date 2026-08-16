"""
bottom/backtest/backtest_runner.py
백테스팅 실행 — 4개 시간프레임(1m/3m/5m/15m) 실제 StochRSI 합의 전략 적용.
기존 _mac_tfs bisect 패턴을 1m/3m/5m/15m에 확장 적용.
수수료(0.09%) · 슬리피지(0.02%) · 펀딩비(0.01%/8h) 거래별 PnL에 차감.
Sort by 6개 필터 + Prohibition 필터 적용.
quality_grade_req 는 QualityGrader(Cascade/Zone/Duration/Swing 4축)로 반영.

[P1] Intrabar SL: bar.low/bar.high로 STOP_MARKET 체결 재현 (봉 내부 SL 판정)
[P2] G3 Swing 전달: QualityGrader 호출 시 swing_bull/swing_bear 키 포함
[P3] G4 ATR% TF: 실거래 data_manager 동일 — 1h봉 기준 ATR%
[P4] G6 EMA TF: 실거래 data_manager 동일 — 1h봉 기준 EMA5/EMA50
[P5] Phase3 50% 부분익절: PARTIAL 거래 기록 후 잔량 50% 트레일링
[P6] G5 volume_ratio TF: 실거래 data_manager 동일 — 1m봉 기준
[P7] G7 Swing 구조 TF: 실거래 data_manager 동일 — 15m봉 6개 기준
[P8] KD 역전 익절: Phase3에서 1m K>80+K<D(롱) / K<20+K>D(숏) 조기 청산
[P9] 3연패 쿨다운: _MAX_CONSECUTIVE_LOSSES 연속 손실 시 300봉 진입 억제
"""
from __future__ import annotations

import bisect

from bottom.backtest.historical_data_loader import HistoricalDataLoader
from bottom.engine_core.quality_grader import QualityGrader
from bottom.engine_core.risk_manager import RiskManager as _RM
from bottom.engine_core.sl_calculator import SLCalculator
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

# 기간별 4TF + 1h 로드 봉 수 (StochRSI 웜업 + 실 검사 구간 합산)
# [P3][P4] 1h봉 추가 — 실거래 data_manager와 동일하게 ATR%·EMA 소스 통일
_TF_BARS: dict[str, dict[str, int]] = {
    "7일":  {"1m": 10320, "3m": 3450, "5m": 2100, "15m":  710, "1h":  225},
    "14일": {"1m": 20400, "3m": 6820, "5m": 4100, "15m": 1380, "1h":  390},
    "30일": {"1m": 43400, "3m":14500, "5m": 8700, "15m": 2920, "1h":  780},
    "90일": {"1m":129600, "3m":43220, "5m":25960, "15m": 8680, "1h": 1500},
}

# 합의 모드 상수
_CONSENSUS_4_4 = "4/4"       # 4개 TF 모두 합의 (4/4)
_CONSENSUS_3_4 = "3/4"       # 3개 이상 TF 합의 (3/4 과반)

# 비용 상수 (거래별 레버리지 반영 PnL%에서 차감)
_COMMISSION   = 0.0004    # 테이커 수수료 0.040% / 편도 (Binance USDT-M)
_SLIPPAGE     = 0.00010   # 슬리피지 0.010% / 편도 (시장 충격 추정)
_FUNDING_RATE = 0.0001    # 펀딩비 0.01% / 8시간 (표준 중립 추정)
_FUNDING_BARS = 480       # 8시간 = 480개 1m봉

# EMA / ATR / 거래량 계산 윈도우
_EMA_SHORT  = 5
_EMA_LONG   = 50
_ATR_PERIOD = 14
_VOL_PERIOD = 20

# Prohibition 임계값
_FR_THRESHOLD = 0.05    # FR 임계값 (%) — prohibition_filter.py 동일
_NEW_DAYS_BAN = 14
# common_liq — liquidation_proximity.py 동일 상수
_LIQ_GAUGE_MAX = 5.0    # LiquidationProximityPanel.GAUGE_MAX_PCT
_LIQ_BASE_MULT = 2.0    # LiquidationProximityPanel.BASE_MULTIPLIER
_LIQ_FR_BIAS   = 0.3    # LiquidationProximityPanel.FR_BIAS_FACTOR
# quality_grade_req 등급 서열 — A(0) 가장 엄격, D(3) 최완화
_GRADE_ORDER  = {"A": 0, "B": 1, "C": 2, "D": 3}
# common_macro HTF StochRSI 파라미터 (실거래 엔진 동일)
_MAC_KD_PARAMS = (14, 14, 3, 3)

# [P9] 연패 쿨다운 — 실거래 trading_engine.py 동일 설정
_MAX_CONSECUTIVE_LOSSES = 3     # N연패 시 쿨다운 진입
_LOSS_COOLDOWN_BARS     = 5     # 쿨다운 지속 봉 수 (5분 = 5 × 1m봉)

# [B-6] 일일 손실 정지 — risk_manager.py MAX_DAILY_LOSS_PCT 동일
_MAX_DAILY_LOSS_PCT = 30.0           # 일일 최대 손실 한도 (%)
_KST_OFFSET_MS      = 9 * 3600 * 1000  # KST = UTC+9 (ms 단위)


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
    Phase1(초기SL) → Phase2(BEP이동) → Phase3(50%부분익절+트레일링) 청산 시뮬레이션.
    [P1] 모든 SL 판정에 bar.low/bar.high 사용 — 봉 내부(intrabar) STOP_MARKET 체결 재현.
    """

    @classmethod
    def load_tf_bars(cls, symbol: str, period: str = "7일") -> dict:
        """5개 TF 봉 데이터를 1회 로드 — run_comparison에서 API 5배 호출 방지."""
        bars_cfg = _TF_BARS.get(period, _TF_BARS["7일"])
        return {
            "1m":  HistoricalDataLoader.load_bars(symbol, "1m",  bars_cfg["1m"]),
            "3m":  HistoricalDataLoader.load_bars(symbol, "3m",  bars_cfg["3m"]),
            "5m":  HistoricalDataLoader.load_bars(symbol, "5m",  bars_cfg["5m"]),
            "15m": HistoricalDataLoader.load_bars(symbol, "15m", bars_cfg["15m"]),
            "1h":  HistoricalDataLoader.load_bars(symbol, "1h",  bars_cfg["1h"]),
        }

    @classmethod
    def run(cls, symbol: str, params: StrategyParams, period: str = "7일",
            consensus_mode: str = _CONSENSUS_4_4,
            preloaded: "dict | None" = None) -> BacktestResult:
        period_days = cls._days(period)
        bars_cfg    = _TF_BARS.get(period, _TF_BARS["7일"])

        # ── 5개 TF 봉 로드 (preloaded 제공 시 API 호출 생략) ──────
        if preloaded is not None:
            bars_1m  = preloaded["1m"]
            bars_3m  = preloaded["3m"]
            bars_5m  = preloaded["5m"]
            bars_15m = preloaded["15m"]
            # [P3][P4] 1h봉 — preloaded에 없으면 개별 로드
            bars_1h  = preloaded.get("1h") or HistoricalDataLoader.load_bars(
                symbol, "1h", bars_cfg.get("1h", 225))
        else:
            bars_1m  = HistoricalDataLoader.load_bars(symbol, "1m",  bars_cfg["1m"])
            bars_3m  = HistoricalDataLoader.load_bars(symbol, "3m",  bars_cfg["3m"])
            bars_5m  = HistoricalDataLoader.load_bars(symbol, "5m",  bars_cfg["5m"])
            bars_15m = HistoricalDataLoader.load_bars(symbol, "15m", bars_cfg["15m"])
            bars_1h  = HistoricalDataLoader.load_bars(symbol, "1h",  bars_cfg.get("1h", 225))

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

        # ── Sort by 필터 설정 ──────────────────────────────────────
        cfg = get_mode_config(params.sort_mode)

        # [P3] G4 ATR% — 1h봉 기준 (실거래 data_manager: AtrPercent.calculate(b1h) 동일)
        atr_pct_1h: list[float] = cls._calc_atr_series(bars_1h, _ATR_PERIOD) if bars_1h else []
        times_1h:   list        = [b.open_time for b in bars_1h] if bars_1h else []

        # [P6] G5 volume_ratio — 1m봉 기준 (실거래 data_manager: b1m_kr[-1].volume 동일)
        vol_ratio_1m: list[float] = []
        if cfg.volume_mult is not None:
            vol_ratio_1m = cls._calc_vol_ratio_series(bars_1m, _VOL_PERIOD)

        # [P4] G6 EMA — 1h봉 기준 (실거래 data_manager: EMAAlignment.calculate(b1h) 동일)
        ema5_1h:  list[float] = []
        ema50_1h: list[float] = []
        if cfg.macro_ema and bars_1h:
            closes_1h = [b.close for b in bars_1h]
            ema5_1h   = cls._calc_ema_series(closes_1h, _EMA_SHORT)
            ema50_1h  = cls._calc_ema_series(closes_1h, _EMA_LONG)

        # ── common_new 상장 일수 ─────────────────────────────────
        _days_listed = 9999
        if params.prohibition.common_new:
            _dlisted     = HistoricalDataLoader.load(symbol, "1d", _NEW_DAYS_BAN + 5)
            _days_listed = len(_dlisted)

        # ── common_macro·use_macro HTF StochRSI (기존 bisect 패턴 유지) ─
        _mac_tfs: list = []
        if params.use_macro:
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

        # ── common_fr 펀딩비 이력 로드 ───────────────────────────────
        _fr_times:    list[int]   = []
        _fr_pct_list: list[float] = []
        if params.prohibition.common_fr or params.prohibition.common_liq:
            _fr_times, _fr_pct_list = HistoricalDataLoader.load_funding_rate(symbol)

        # ── common_liq L/S ratio 이력 로드 ──────────────────────────
        _lr_times:    list[int]   = []
        _lr_long_pct: list[float] = []
        if params.prohibition.common_liq:
            _lr_times, _lr_long_pct = HistoricalDataLoader.load_long_short_ratio(symbol)

        # [P7] G7 Swing 구조 — 15m봉 기준 bisect용 시간 시리즈
        times_15m: list = [b.open_time for b in bars_15m]

        # ── 메인 루프 상태 초기화 ──────────────────────────────────
        trades:     list[BacktestTrade] = []
        _tf_min   = 3

        in_long     = False
        in_short    = False
        entry_price = 0.0
        entry_time  = 0
        entry_bar_i = 0
        phase       = 1
        trail_ref   = 0.0

        # [P9] 연패 쿨다운 상태 — 실거래 trading_engine.py 동일 설계
        _consecutive_losses = 0
        _cooldown_until_bar = 0

        # [B-6] 일일 손실 정지 상태 — KST 일 경계 기준
        _daily_pnl_usdt = 0.0   # 당일 누적 PnL (USDT)
        _daily_date_key = -1    # 추적 중인 날짜 (KST 일 단위 정수)

        # [C-2] SL/Trail 사전 계산 — liq_safe 상한 적용. leverage·mmr 불변 → 루프 전 1회 계산
        sl_used, trail_used = SLCalculator.clamp(
            params.stop_loss, params.trail_stop, params.leverage, mmr=params.mmr)

        # [C-1] 유효 레버리지 사전 계산 — R-cap(8%) 반영 (결정2-a / 결정1-a)
        # P 소거 원리: mark=1.0 사용 가능 (mark 값에 관계없이 L_eff 동일)
        _alloc   = params.portfolio_usdt * params.funds_pct / 100.0
        _qty0    = _RM.calc_position_size(params, 1.0, params.portfolio_usdt)
        _qty_cap = _RM.apply_r_cap(_qty0, 1.0, sl_used, params.portfolio_usdt)
        _leff    = (_qty_cap / _alloc) if _alloc > 0 else float(params.leverage)

        # tf5 교차 시점 추적 — QualityGrader _duration_score 재현용
        _tf5_long_cross_t:  float = 0.0
        _tf5_short_cross_t: float = 0.0
        _prev_tf5_long_ok:  bool  = False
        _prev_tf5_short_ok: bool  = False

        n_1m = len(bars_1m)
        for i in range(_WARMUP_1M, n_1m):
            bar   = bars_1m[i]
            close = bar.close
            t     = bar.open_time

            # [B-6] KST 일 경계 감지 → 당일 누적 PnL 리셋
            _bar_day = (t + _KST_OFFSET_MS) // 86_400_000
            if _bar_day != _daily_date_key:
                _daily_pnl_usdt = 0.0
                _daily_date_key = _bar_day

            # ── [P3] 1h 기준 ATR% bisect 조회 ──────────────────────
            pos_1h  = max(0, bisect.bisect_left(times_1h, t) - 1) if times_1h else 0
            atr_pct = atr_pct_1h[pos_1h] if (times_1h and pos_1h < len(atr_pct_1h)) else 0.0
            atr_ok  = cfg.atr_min <= atr_pct <= cfg.atr_max

            # ── [P6] 1m 기준 volume_ratio 직접 조회 ─────────────────
            vol_ok = True
            if cfg.volume_mult is not None and vol_ratio_1m:
                vr     = vol_ratio_1m[i] if i < len(vol_ratio_1m) else 1.0
                vol_ok = vr >= cfg.volume_mult

            # ── [FR] common_fr 펀딩비 진입 차단 판정 ─────────────────
            fr_ok_long  = True
            fr_ok_short = True
            if params.prohibition.common_fr and _fr_times:
                _fr_pos = max(0, bisect.bisect_left(_fr_times, t) - 1)
                _fr_val = _fr_pct_list[_fr_pos] if _fr_pos < len(_fr_pct_list) else 0.0
                fr_ok_long  = _fr_val <= _FR_THRESHOLD
                fr_ok_short = _fr_val >= -_FR_THRESHOLD

            # ── [LIQ] common_liq 청산 근접도 판정 ────────────────────
            liq_ok_long  = True
            liq_ok_short = True
            if params.prohibition.common_liq:
                _liq_fr_val = 0.0
                if _fr_times:
                    _liq_fr_pos = max(0, bisect.bisect_left(_fr_times, t) - 1)
                    _liq_fr_val = _fr_pct_list[_liq_fr_pos] if _liq_fr_pos < len(_fr_pct_list) else 0.0
                _liq_base      = max(atr_pct * _LIQ_BASE_MULT, 1.0)
                _lr_long_pct_v = 50.0
                if _lr_times:
                    _lr_pos = max(0, bisect.bisect_left(_lr_times, t) - 1)
                    if _lr_pos < len(_lr_long_pct):
                        _lr_long_pct_v = _lr_long_pct[_lr_pos]
                _long_excess  = max(0.0, (_lr_long_pct_v - 50.0) / 50.0)
                _short_excess = max(0.0, (50.0 - _lr_long_pct_v) / 50.0)
                liq_long_dist  = max(0.5, min(_LIQ_GAUGE_MAX,
                                     _liq_base - (abs(_liq_fr_val) * _LIQ_FR_BIAS if _liq_fr_val > 0 else 0.0)
                                     - _long_excess * _liq_base * 0.5))
                liq_short_dist = max(0.5, min(_LIQ_GAUGE_MAX,
                                     _liq_base - (abs(_liq_fr_val) * _LIQ_FR_BIAS if _liq_fr_val < 0 else 0.0)
                                     - _short_excess * _liq_base * 0.5))
                liq_safe       = min(sl_used, _LIQ_GAUGE_MAX * 0.95)
                liq_ok_long    = liq_long_dist  >= liq_safe
                liq_ok_short   = liq_short_dist >= liq_safe

            # ── [P8] 1m TF K/D — KD 역전 익절 판정용 ───────────────
            _k1m = _d1m = 50.0
            _1m_entry = tf_data.get("1m")
            if _1m_entry:
                _1m_times, _1m_off, _1m_ks, _1m_ds = _1m_entry
                _pos1 = bisect.bisect_left(_1m_times, t) - 1
                _idx1 = _pos1 - _1m_off
                if 0 <= _idx1 < len(_1m_ks):
                    _k1m, _d1m = _1m_ks[_idx1], _1m_ds[_idx1]

            # ── 롱 포지션 관리 ────────────────────────────────────
            if in_long:
                bars_held = i - entry_bar_i
                R         = entry_price * sl_used / 100.0
                sl_phase1 = entry_price * (1.0 - sl_used / 100.0)

                if phase == 1:
                    # [P1] intrabar: bar.low ≤ sl_phase1 → STOP_MARKET 체결 재현
                    if bar.low <= sl_phase1:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (sl_phase1 - entry_price) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=sl_phase1,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="SL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-4] Phase1→2 intrabar: bar.high 기준 (실거래 Binance 서버측 체결 재현)
                    if bar.high >= entry_price + R:
                        phase = 2

                elif phase == 2:
                    # [P1] intrabar: bar.low ≤ entry_price → BEP STOP_MARKET 체결 재현
                    if bar.low <= entry_price:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (entry_price - entry_price) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=entry_price,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="BEP-SL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-4][P5] Phase2→3 intrabar: bar.high 기준, trail_ref=트리거 가격
                    if bar.high >= entry_price + R * 1.5:
                        cost_p = cls._cost(_leff, bars_held)
                        pnl_p  = (close - entry_price) / entry_price * 100.0 * _leff - cost_p
                        _pnl_usdt_val_p = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl_p / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(0.5 * pnl_p, 3),  # [A-3] 50% 물량 가중
                            pnl_usdt=_pnl_usdt_val_p,
                            exit_reason="PARTIAL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val_p  # [B-6]
                        _consecutive_losses = 0
                        phase = 3; trail_ref = entry_price + R * 1.5  # [A-4] 트리거 가격 기준

                elif phase == 3:
                    # [A-5] TRAIL 체크 먼저 (실거래: Binance TRAILING_STOP_MARKET 서버측 선행 체결)
                    trail_ref = max(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 - trail_used / 100.0)
                    # [P1] intrabar + [P5] 잔량 50%: bar.low ≤ trail_sl → trailing stop 체결 재현
                    if bar.low <= trail_sl:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (trail_sl - entry_price) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=trail_sl,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="TRAIL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-5][P8] TRAIL이 없을 때만 KD 역전 익절 체크
                    if _k1m > 80.0 and _k1m < _d1m and (_d1m - _k1m) >= 2.0:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (close - entry_price) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="long", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="KD-EXIT",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        _consecutive_losses = 0
                        in_long = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 숏 포지션 관리 ────────────────────────────────────
            elif in_short:
                bars_held = i - entry_bar_i
                R         = entry_price * sl_used / 100.0
                sl_phase1 = entry_price * (1.0 + sl_used / 100.0)

                if phase == 1:
                    # [P1] intrabar: bar.high ≥ sl_phase1 → STOP_MARKET 체결 재현
                    if bar.high >= sl_phase1:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (entry_price - sl_phase1) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=sl_phase1,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="SL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-4] Phase1→2 intrabar: bar.low 기준 (실거래 Binance 서버측 체결 재현)
                    if bar.low <= entry_price - R:
                        phase = 2

                elif phase == 2:
                    # [P1] intrabar: bar.high ≥ entry_price → BEP STOP_MARKET 체결 재현
                    if bar.high >= entry_price:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (entry_price - entry_price) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=entry_price,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="BEP-SL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-4][P5] Phase2→3 intrabar: bar.low 기준, trail_ref=트리거 가격
                    if bar.low <= entry_price - R * 1.5:
                        cost_p = cls._cost(_leff, bars_held)
                        pnl_p  = (entry_price - close) / entry_price * 100.0 * _leff - cost_p
                        _pnl_usdt_val_p = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl_p / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(0.5 * pnl_p, 3),  # [A-3] 50% 물량 가중
                            pnl_usdt=_pnl_usdt_val_p,
                            exit_reason="PARTIAL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val_p  # [B-6]
                        _consecutive_losses = 0
                        phase = 3; trail_ref = entry_price - R * 1.5  # [A-4] 트리거 가격 기준

                elif phase == 3:
                    # [A-5] TRAIL 체크 먼저 (실거래: Binance TRAILING_STOP_MARKET 서버측 선행 체결)
                    trail_ref = min(trail_ref, close)
                    trail_sl  = trail_ref * (1.0 + trail_used / 100.0)
                    # [P1] intrabar + [P5] 잔량 50%: bar.high ≥ trail_sl → trailing stop 체결 재현
                    if bar.high >= trail_sl:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (entry_price - trail_sl) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=trail_sl,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="TRAIL",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        if pnl < 0:
                            _consecutive_losses += 1
                            if _consecutive_losses >= _MAX_CONSECUTIVE_LOSSES:
                                _cooldown_until_bar = i + _LOSS_COOLDOWN_BARS
                                _consecutive_losses = 0  # [A-2]
                        else:
                            _consecutive_losses = 0
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue
                    # [A-5][P8] TRAIL이 없을 때만 KD 역전 익절 체크
                    if _k1m < 20.0 and _k1m > _d1m and (_k1m - _d1m) >= 2.0:
                        cost = cls._cost(_leff, bars_held)
                        pnl  = (entry_price - close) / entry_price * 100.0 * _leff - cost
                        _pnl_usdt_val = round(0.5 * params.portfolio_usdt * params.funds_pct / 100.0 * pnl / 100.0, 4)
                        trades.append(BacktestTrade(
                            entry_time=entry_time, exit_time=bar.close_time,
                            side="short", entry_price=entry_price, exit_price=close,
                            pnl_pct=round(pnl, 3),
                            pnl_usdt=_pnl_usdt_val,
                            exit_reason="KD-EXIT",
                        ))
                        _daily_pnl_usdt += _pnl_usdt_val  # [B-6]
                        _consecutive_losses = 0
                        in_short = False; phase = 1; trail_ref = 0.0
                        continue

            # ── 신규 진입 (포지션 없을 때만) ─────────────────────
            if not in_long and not in_short:
                # [B-6] 일일 손실 정지 — 당일 누적 PnL이 -30% 이하이면 진입 억제
                if _daily_pnl_usdt / params.portfolio_usdt * 100.0 <= -_MAX_DAILY_LOSS_PCT:
                    continue
                # [P9] 연패 쿨다운 — _MAX_CONSECUTIVE_LOSSES 연속 손실 시 진입 억제
                if i < _cooldown_until_bar:
                    continue

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

                # [P7] G7 Swing — 15m봉 기준 bisect (실거래 data_manager: b15m_kr[-6:] 동일)
                _pos_15m  = max(0, bisect.bisect_left(times_15m, t) - 1)
                _sw_long  = cls._swing_bull(bars_15m, _pos_15m)
                _sw_short = cls._swing_bear(bars_15m, _pos_15m)

                # ── 롱 진입 시도 ──────────────────────────────────
                if (can_long
                        and k_5m < cfg.k_long_max
                        and cfg.direction_bias != "short_only"
                        and atr_ok and vol_ok
                        and not (params.prohibition.common_new and _days_listed < _NEW_DAYS_BAN)
                        and fr_ok_long
                        and liq_ok_long
                        and _mac_ok_long):
                    # [P4] G6 EMA — 1h봉 기준 (실거래 data_manager 동일)
                    ema_ok = True
                    if cfg.macro_ema and ema50_1h:
                        e5  = ema5_1h[pos_1h]  if pos_1h < len(ema5_1h)  else 0.0
                        e50 = ema50_1h[pos_1h] if pos_1h < len(ema50_1h) else 0.0
                        ema_ok = (e5 > e50) if e50 > 0 else True

                    # G7: requires_swing 모드 — 15m swing 구조 확인
                    swing_ok = (not cfg.requires_swing) or _sw_long

                    if ema_ok and swing_ok:
                        grade_ok = True
                        if cfg.quality_grade_req is not None:
                            _em_l = (t - _tf5_long_cross_t) / 60_000 if _tf5_long_cross_t > 0 else -1
                            _el_l = _fmt_elapsed(_em_l)
                            # [P2] G3: swing_bull 키 포함 — QualityGrader Swing 보너스 25점 재현
                            _ind_l = {
                                "tf1":  {"k": tf_kd.get("1m",  (50.0, 50.0))[0], "d": tf_kd.get("1m",  (50.0, 50.0))[1]},
                                "tf3":  {"k": tf_kd.get("3m",  (50.0, 50.0))[0], "d": tf_kd.get("3m",  (50.0, 50.0))[1]},
                                "tf5":  {"k": tf_kd.get("5m",  (50.0, 50.0))[0], "d": tf_kd.get("5m",  (50.0, 50.0))[1], "elapsed": _el_l},
                                "tf15": {"k": tf_kd.get("15m", (50.0, 50.0))[0], "d": tf_kd.get("15m", (50.0, 50.0))[1]},
                                "swing_bull": _sw_long,
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
                        and fr_ok_short
                        and liq_ok_short
                        and _mac_ok_short):
                    # [P4] G6 EMA — 1h봉 기준 (실거래 data_manager 동일)
                    ema_ok = True
                    if cfg.macro_ema and ema50_1h:
                        e5  = ema5_1h[pos_1h]  if pos_1h < len(ema5_1h)  else 0.0
                        e50 = ema50_1h[pos_1h] if pos_1h < len(ema50_1h) else 0.0
                        ema_ok = (e5 < e50) if e50 > 0 else True

                    # G7: requires_swing 모드 — 15m swing 구조 확인
                    swing_ok = (not cfg.requires_swing) or _sw_short

                    if ema_ok and swing_ok:
                        grade_ok = True
                        if cfg.quality_grade_req is not None:
                            _em_s = (t - _tf5_short_cross_t) / 60_000 if _tf5_short_cross_t > 0 else -1
                            _el_s = _fmt_elapsed(_em_s)
                            # [P2] G3: swing_bear 키 포함 — QualityGrader Swing 보너스 25점 재현
                            _ind_s = {
                                "tf1":  {"k": tf_kd.get("1m",  (50.0, 50.0))[0], "d": tf_kd.get("1m",  (50.0, 50.0))[1]},
                                "tf3":  {"k": tf_kd.get("3m",  (50.0, 50.0))[0], "d": tf_kd.get("3m",  (50.0, 50.0))[1]},
                                "tf5":  {"k": tf_kd.get("5m",  (50.0, 50.0))[0], "d": tf_kd.get("5m",  (50.0, 50.0))[1], "elapsed": _el_s},
                                "tf15": {"k": tf_kd.get("15m", (50.0, 50.0))[0], "d": tf_kd.get("15m", (50.0, 50.0))[1]},
                                "swing_bear": _sw_short,
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
        result = ResultSummary.build(symbol, params.sort_mode, period_days, trades)
        if params.prohibition.common_liq and _lr_times:
            result.long_ratio_coverage = round(
                len(_lr_times) / max(1, period_days * 288) * 100.0, 1)
        return result

    @classmethod
    def run_comparison(
        cls,
        symbol: str,
        params: StrategyParams,
        period: str = "7일",
    ) -> "dict[str, BacktestResult]":
        """2가지 합의 모드 동시 비교 실행 — 봉 데이터 1회 로드 후 2모드 공유.

        Returns
        -------
        dict: 모드별 BacktestResult
            키: '4/4', '3/4'
        """
        preloaded = cls.load_tf_bars(symbol, period)
        results: dict[str, BacktestResult] = {}
        for mode in (_CONSENSUS_3_4, _CONSENSUS_4_4):
            results[mode] = cls.run(symbol, params, period,
                                    consensus_mode=mode, preloaded=preloaded)
        return results

    # ── 거래 비용 계산 ──────────────────────────────────────────
    @staticmethod
    def _cost(leverage: float, bars_held: int) -> float:
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