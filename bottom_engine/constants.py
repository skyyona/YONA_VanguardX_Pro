"""
bottom_engine/constants.py
앱 전체 공유 상수 — 단일 선언 소스.
이 파일은 아무것도 import하지 않는다 (circular import 방지).

middle 모듈 liquidation_proximity.py 의 GAUGE_MAX_PCT / BASE_MULTIPLIER / FR_BIAS_FACTOR
와 동일 값(_LIQ_GAUGE_MAX / _LIQ_BASE_MULT / _LIQ_FR_BIAS)을 선언한다.
middle 모듈은 별도 레이어이므로 이 파일을 import하지 않는다 — 값 동기화는 수동 유지.
"""
from __future__ import annotations

# ── 리스크 한도 ──────────────────────────────────────────────────────────────
# KST 자정 기준 일일 최대 실현 손실 한도 (%). R=8% 기준 3연패(-22.1%)를 허용하고
# 5연패(-34.1%)에서 정지. 20.0이면 3연패에서 발동해 R=8% 정책과 충돌하므로 반드시 30.0 유지.
MAX_DAILY_LOSS_PCT      = 30.0
# 단일 거래 최대 손실 비율 — SL 도달 시 손실이 이 값 초과 시 수량 상한 조정 (%)
_MAX_R_PCT              = 8.0
# Binance USDT-M Futures 테이커 수수료율 (편도)
_TAKER_FEE_RATE         = 0.0004

# ── 거래 금지 필터 임계값 ────────────────────────────────────────────────────
# FR 과밀/음수 임계값 (%)
_FR_THRESHOLD           = 0.05
# 신규 상장 최소 거래 가능 일수
_NEW_DAYS_MIN           = 14
# 청산 근접도 게이지 최대 거리 (%) — liquidation_proximity.py GAUGE_MAX_PCT 동기화
_LIQ_GAUGE_MAX          = 5.0

# ── 청산 근접도 계산 파라미터 ─────────────────────────────────────────────────
# ATR 대비 청산 구간 기본 배수 — liquidation_proximity.py BASE_MULTIPLIER 동기화
_LIQ_BASE_MULT          = 2.0
# FR 방향 추가 위험 보정 계수 — liquidation_proximity.py FR_BIAS_FACTOR 동기화
_LIQ_FR_BIAS            = 0.3

# ── 거래 로직 임계값 ─────────────────────────────────────────────────────────
# Phase3 trail 활성화 지연 임계값 (%) — trading_engine.py·backtest_runner.py 공유
_PROFIT_TRIGGER_PCT     = 1.0
# 연패 쿨다운 진입 N값 — trading_engine.py·backtest_runner.py 공유
_MAX_CONSECUTIVE_LOSSES = 3
# StochRSI K-D 최소 스프레드 — fourtf_consensus.py·backtest_runner.py 공유
_MIN_SPREAD             = 2.0
