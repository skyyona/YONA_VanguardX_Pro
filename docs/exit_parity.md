# BT ↔ LIVE 청산 로직 잔존 불일치 문서

작성: 2026-09-25  
관련 파일: `bottom_engine/strategy/m4_exit.py`, `bottom_engine/backtest/backtest_runner.py`,  
           `bottom_engine/long_engine/long_position.py`, `bottom_engine/short_engine/short_position.py`

---

## 개요

PART 2 (방안 A) 구현으로 BT·LIVE 공통 청산 판정을 `M4Exit.evaluate()`로 단일화했다.  
아래 ⑦~⑩은 구조적 또는 미세한 차이로 남아 있으며, **의도적으로 허용된 항목**이다.

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
| LIVE | Binance 서버: `TRAILING_STOP_MARKET` 주문을 서버가 처리 |

**영향**: Binance 서버 체결은 실제 시장 틱 레벨에서 발생하고, BT는 5분봉 intrabar 재현.  
슬리피지 모델링 차이이며 전략 로직 자체의 불일치가 아님.  
**허용 이유**: BT에서 tick-level 시뮬레이션은 과도한 복잡성이며, 기존 BT 설계 원칙과 일치.

---

### ⑩ -16% 백스탑 (긴급 청산)

| 구분 | 적용 여부 |
|------|----------|
| BT   | 없음 |
| LIVE | `risk_manager.py`: 마진 -16% 이하 시 강제 청산 |

**영향**: 극단적 시장 이벤트(플래시 크래시 등)에서 BT는 SL까지 보유, LIVE는 -16%에서 강제 청산.  
정상적인 거래 범위에서는 발동하지 않으며 BT 성과 지표에 미치는 영향 미미.  
**허용 이유**: LIVE 전용 리스크 안전망으로 BT 목적(전략 성과 측정)과 범위가 다름.

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
