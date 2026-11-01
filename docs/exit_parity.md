# BT ↔ LIVE 청산 로직 잔존 불일치 문서

작성: 2026-09-25  
갱신: 2026-10-27 (⑨⑩ 정정, ⑪⑱ 추가, 정합성 수정 5건·미해결 ⑲⑳ 추가)  
관련 파일: `bottom_engine/strategy/m4_exit.py`, `bottom_engine/backtest/backtest_runner.py`,  
           `bottom_engine/long_engine/long_position.py`, `bottom_engine/short_engine/short_position.py`

---

## 개요

PART 2 (방안 A) 구현으로 BT·LIVE 공통 청산 판정을 `M4Exit.evaluate()`로 단일화했다.  
아래 ⑦~⑪·⑱은 구조적 또는 미세한 차이로 남아 있으며, **의도적으로 허용된 항목**이다.

---

## 잔존 불일치 목록

### ⑦ trail_ref 갱신 기준가

| 구분 | 값 |
|------|----|
| BT   | `bar.close` (5분봉 종가) |
| LIVE | `mark` (현재 마크 프라이스) |

**영향**: 동일한 `M4Exit.evaluate()` 코드를 공유하며, 호출 시 전달하는 `close` 값만 다르다.  
5분봉 내에서 `mark`와 `bar.close`의 차이가 미세하여 실질 영향 없음.  
**허용 이유**: LIVE는 Binance mark price 연속 수신, BT는 완성된 봉 데이터 재현이라는 구조적 차이.

---

### ⑧ profit_trigger 도달 판정

| 구분 | 값 |
|------|----|
| BT   | `close >= profit_trigger` (`bar.close` 기준) |
| LIVE | `close >= profit_trigger` (`mark` 기준, `profit_trigger=0.0` 전달로 즉시 활성) |

**영향**: LIVE에서는 `profit_trigger=0.0`으로 전달하므로 `trail_active=True` 항상 성립.  
실제 profit_trigger 관리는 `_sl_loop()`의 엔진 레벨에서 담당.  
**허용 이유**: LIVE profit_trigger는 엔진이 관리하는 별도 상태이며, BT에서만 per-bar 체크가 의미 있음.

---

### ⑨ TRAIL 집행 방식

| 구분 | 방식 |
|------|------|
| BT   | client-side: `bar.high >= trail_sl` 조건 시 `BacktestTrade` 기록 |
| LIVE | Binance 서버: `TRAILING_STOP_MARKET` **Algo 주문**(`/fapi/v1/algoOrder`, `bottom_engine/api/binance_client.py` `place_trailing_stop()`)을 서버가 처리 |

**영향**: Binance 서버 체결은 실제 시장 틱 레벨에서 발생하고, BT는 5분봉 intrabar 재현.  
**주문 경로**: 2025-12-09부터 조건부 주문은 `/fapi/v1/order`에서 -4120으로 거절되므로 SL·Trailing 모두 Algo 주문으로 전환 (커밋 `c11a1cd`).  
슬리피지 모델링 차이이며 전략 로직 자체의 불일치가 아님.  
**허용 이유**: BT에서 tick-level 시뮬레이션은 과도한 복잡성이며, 기존 BT 설계 원칙과 일치.

---

### ⑩ -16% 백스탑 (긴급 청산)

| 구분 | 적용 여부 |
|------|----------|
| BT   | 없음 |
| LIVE | `trading_engine.py:1529-1540` (`_sync_position_with_binance()`): 미실현 손익 / 잔고 < −16% 시 시장가 청산, 청산 사유 `BACKSTOP` |

**영향**: 극단적 시장 이벤트(플래시 크래시 등)에서 BT는 SL까지 보유, LIVE는 -16%에서 강제 청산.  
정상적인 거래 범위에서는 발동하지 않으며 BT 성과 지표에 미치는 영향 미미.  
**허용 이유**: LIVE 전용 리스크 안전망으로 BT 목적(전략 성과 측정)과 범위가 다름.

---

### ⑪ KD-EXIT 판정·체결 시점

| 구분 | 값 |
|------|----|
| BT   | 5m 경계의 1m 봉 i 마감 시각에 판정, 청산가 = 봉 i 종가 |
| LIVE | 5m 봉 마감 → WS 최종 봉 캐시 반영(실측 0.07~3.07초) → `_sl_loop()` 다음 주기(`SL_INTERVAL_SEC = 1`)에 판정, 청산가 = `mark` 시장가 |

**영향**: 판정에 쓰는 지표(마감 봉까지의 5m K)는 양쪽 동일하며(커밋 `65cc2f2`), 남는 차이는 체결 시점 약 0.07~4초와 종가↔시장가 차이뿐.  
**허용 이유**: 봉 마감 후 데이터 수신·주문 전송에 필요한 최소 지연으로, 슬리피지 모델(`_SLIPPAGE`) 범위의 구조적 차이.

---

### ⑱ 진입 체결 시점

| 구분 | 값 |
|------|----|
| BT   | 1m 봉 i 마감 시각에 판정, 진입가 = 봉 i 종가 |
| LIVE | 1m 경계 → 마감 봉 반영 대기(`_wait_bar_close()`, 실측 0.07~3.07초, WS 미도착 시 4·7초 REST 강제 갱신, 10초 초과 시 해당 봉 판단 건너뜀) → 판정 → 시장가 진입 |

**영향**: 판정 지표는 양쪽 동일(커밋 `65cc2f2`, 실연동 16/16 경계 REST 확정값 재계산과 완전 일치). 남는 차이는 체결 시점 약 0.07~3초와 종가↔시장가 차이.  
**허용 이유**: ⑪과 동일.

---

## 통일된 항목 (PART 2 완료)

| 항목 | 이전 | 이후 |
|------|------|------|
| Phase 전환 임계값 | BT·LIVE 별도 인라인 로직 | `M4Exit.evaluate()` 공통 |
| SL Phase1 기준 | BT: `sl_phase1` 변수, LIVE: `current_sl` | 동일 공식 `entry*(1±sl_pct/100)` |
| BEP-SL Phase2 | BT: `entry_price`, LIVE: `pos.current_sl` | 동일 `entry` 기준 |
| PARTIAL Phase3 진입 기준 | BT: `entry - R*1.5`, LIVE: 독립 계산 | 동일 `entry ± R*1.5` |
| KD exit 조건 | BT: `k_prev`/`k_cur` 인라인, LIVE: `_sl_loop` | BT=M4Exit, LIVE=`_sl_loop` (구조 명확화) |
| trail_ref 추적 방향 | LONG=max, SHORT=min | `M4Exit` 내부에서 통일 |

---

## 정합성 수정 완료 (이후)

| 차이 | 내용 | 해결 방법 | 커밋 |
|------|------|-----------|------|
| ⑬ | LIVE G2 가 진행 중 15m 봉 사용 | `trading_engine.py:726` 마감 봉 필터 추가 | `0ce260d` |
| ⑭ | Phase2 전환 시 KD-EXIT — BT/LIVE 불일치 | `m4_exit.py:112,177` `new_phase == 1 and …` 조건, `trading_engine.py:578` `(old_phase_l != 1 or updated.phase != 2)` 가드 — 양쪽 모두 `close >= entry` 수익 조건 포함 | 기수정 |
| ⑮ | `phase1_timeout_bars` 단위 5배 불일치 (BT `bars_held` 1m vs LIVE `_elapsed_5m` 5m) | BT 비교식에 `* 5` 추가 | `4ebe270` |
| ⑯ | BT `common_liq liq_safe` K 계수 불일치 (K=0.75 → K=1.0) | BT `min(sl_used, _LIQ_GAUGE_MAX * 0.95)` 로 일치 | `6bf1cd6` |
| — | LIVE 5m StochRSI 계산 봉 수가 BT와 다름 + 중단 갱신 경로 간 경합 | 중단 5m klines 199봉으로 통일, 경합 제거 | `6edb677` |
| — | LIVE 1m·3m·15m·1h·4h·1d 계산 봉 수가 BT와 다름(G6·G7.5·G_ema·G4 입력) + 15m 경로 간 경합(59/79봉) + `get_ohlcv` 60봉 캐시 잔존 | `_KLINES_LIMITS` 단일 표 — 1m·3m·5m·15m 199봉 / 1h·4h·1d 79봉, STAGE3·상세·`get_ohlcv` 동일 (1h G_ema 불일치 2.43% 잔존) | `ce31216` |
| — | LIVE 1h EMA50(G_ema) 79봉 SMA 시드 잔존 → BT와 판정 2.43% 불일치 | 1h klines 199봉 (4h·1d 79봉 유지) — G_ema 0.00%, ATR% 최대 0.06%, 실시세 60/60 일치 | `255753e` |
| — | LIVE 지표 계산 반올림(StochRSI RSI 4·K·D 2자리, EMA 6·8자리, 청산 근접 2, 거래량 비율 3, ATR%·펀딩비 4자리) — BT는 반올림 없음 | 계산 반올림 제거, 자릿수는 표시에서만 — StochRSI K·D·ATR% 차이 0, 저가 종목 EMA 동일값 0건 (199봉 창 영향 G_ema 0.02% 잔존) | `a666894` |
| — | BT 펀딩 기록이 단일 요청(limit=360, 약 120일)이라 180일 앞 구간 펀딩 0 | 펀딩 기록 페이지 수집(전 구간) + 비용에 실제 펀딩비 반영 | `0cd12ce` |
| — | LIVE 거래소 측 청산(Algo SL·Trailing 발동)이 무조건 `LIQD`·`mark` 또는 `SL`·`mark`로 기록 | Algo 주문 조회로 `SL`·`actualPrice` / `LIQD`·`mark` 판정 + 실측 슬리피지 기록 | `c83a335` |
| — | 일일·포트폴리오 손실 한도 −30% 동작 | BT·LIVE 모두 경고만 (자동 정지·진입 차단 없음) | `25a8e08` |
| — | 판정 시점·미확정 봉: BT는 봉 i 종가로 진입하면서 지표는 봉 i 시작 시각(`t`) 기준 조회, LIVE는 고정 대기 후 REST 조회로 방금 마감된 봉이 미확정·미포함될 수 있음 (G2 15m RSI 포함) | 양쪽 모두 "봉 i 마감 시각까지 마감된 봉" 기준: BT 지표 조회 키 `bar.close_time`, LIVE WS 최종 봉 접합 + `_wait_bar_close()` + REST 마지막 원소 제외 + 4h·1d WS 구독. SL·KD 스윕 정식 재실행 결론 불변 (`1ecdd82`) | `65cc2f2` |

> **⑫ 항목 철회**: 직전 보고에서 "동일 5m 봉 재진입 가드 부재"를 차이로 제안했으나,  
> BT·LIVE 모두 1m 주기 재평가로 동일하게 동작함이 확인됨 — 차이 아님으로 삭제.

---

## 미해결 항목

### ⑰ 백테스트 포지션 점유 미반영

백테스트는 심볼별로 독립 실행되므로 한 심볼의 포지션이 다른 심볼의 신호를 막지 않습니다.  
실거래는 하단 모듈 단일 인스턴스(`main.py:128`)로 **한 심볼만** 운용하며 `MAX_CONCURRENT_POSITIONS = 1`(`risk_manager.py:21`).  
따라서 **백테스트의 거래 수는 실거래보다 과대 추정**됩니다. 규모는 미측정.

### ⑲ 스프레드 필터 백테스트 미반영

실거래는 배정 단계(중단 Assign)에서 최근 10분 호가 스프레드 중앙값 0.2% 초과 심볼을 차단합니다 (커밋 `0407995`).  
선정 단계 필터이며 백테스트에는 모델링되지 않습니다 (과거 호가 데이터 없음).

### ⑳ 테이커 수수료율

BT 비용은 `_TAKER_FEE_RATE = 0.0004`(0.04%, `bottom_engine/constants.py:20`)이나, Binance VIP0 테이커 수수료는 0.05%입니다.  
BT 비용 과소 추정 가능 — 반영 여부는 사용자 결정 대기.
