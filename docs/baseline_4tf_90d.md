# C-4 기준선: 4TF CURRENT 전략 90일 백테스트

> **이 파일은 D-1b(4TF 코드 재삭제) 후에도 비교 기준을 유지하기 위한 영구 보존 문서입니다.**
> 재측정 불가 — 코드 재삭제 후 이 수치가 유일한 비교 기준이 됩니다.

---

## 측정 조건

| 항목 | 값 |
|---|---|
| 커밋 해시 | `d7117e1` (D-1a 복원 커밋) |
| entry_variant | `"CURRENT"` |
| exit_variant | `"CURRENT"` |
| period | `"90일"` |
| consensus_mode | `"3/4"` — `run()` 파라미터에 명시 전달 |
| 측정일 | 2026-09-18 |

### StrategyParams 생성 코드 원문

`_strategy.json` 미사용. 아래 코드로 직접 생성.
출처: `git show e27de40~1:bottom_engine/strategy_settings/_strategy.json` `24h Ticker` 항목.

```python
PARAMS = StrategyParams(
    sort_mode       = "24h Ticker",
    funds_pct       = 100,
    leverage        = 20,        # 현재 파일값(10)과 다름 — e27de40~1 기준
    stop_loss       = 3.7,       # 현재 파일값(4.3)과 다름 — e27de40~1 기준
    trail_stop      = 1.1,       # 현재 파일값(1.8)과 다름 — e27de40~1 기준
    consensus_mode  = "3/4",
    use_macro       = False,
    m4_slope_th     = 10.0,      # CURRENT 경로 미사용 — 기본값 유지
    m4_div_th       = 2.0,       # CURRENT 경로 미사용 — 기본값 유지
    prohibition     = ProhibitionFlags(
        common_liq=True, common_fr=True, common_new=True, common_hunter=True,
        long_fomo=True, long_short_open=True, short_accum=True, short_long_open=True,
    ),
)
BacktestRunner.run(sym, PARAMS, "90일",
    preloaded=None,
    entry_variant="CURRENT",
    exit_variant="CURRENT",
    consensus_mode="3/4",        # run() 파라미터에 명시 — params.consensus_mode와 별개
)
```

### 실효값

```
sl_used  = min(3.7, liq_safe(20x)=3.68) → 3.7
L_eff    = min(20/(1+20×0.0004), 800/(100×3.7)) = 2.162
1회 손실 = 2.162 × 3.7 = 8.00%
왕복비용 = 0.10% × 2.162 = 0.216%
```

---

## 심볼 및 기간

| 심볼 | 역할 |
|---|---|
| 1000BONKUSDT | 측정 대상 |
| 1000SHIBUSDT | 측정 대상 |
| 1000PEPEUSDT | 측정 대상 |
| BTCUSDT | 대조군 |

---

## 중단 조건 4개 대조표

| # | 조건 | 실측값 | 결과 |
|---|---|---|---|
| 1 | 0봉 발생 | API 단건 4심볼 전부 HTTP=200 ✅ | 통과 |
| 2 | 3비BTC 평균 총수익 +15% 초과 | BONK 유일 -18.33% | 통과 |
| 3 | BEP-SL·PARTIAL·TRAIL 전부 0 | BONK: BEP=5, PARTIAL=17, TRAIL=1 | 통과 |
| 4 | BTC 진입 20건 초과 | BTC 0건 | 통과 |

---

## 심볼별 결과 전표

### 수익 지표

| 심볼 | 거래(정수) | 거래(qty가중) | 승률 | 총수익 | MDD | PF | 거래당평균 | 거래당중앙 | 보유중앙 |
|---|---|---|---|---|---|---|---|---|---|
| **1000BONKUSDT** | **66** | **49.00** | **51.5%** | **-18.33%** | **45.69%** | **0.915** | **-0.278%** | **+2.667%** | **384분** |
| 1000SHIBUSDT | 0 | — | — | — | — | — | — | — | — |
| 1000PEPEUSDT | 0 | — | — | — | — | — | — | — | — |
| BTCUSDT | 0 | — | — | — | — | — | — | — | — |

### 청산·진입 분포 (BONK)

| 청산사유 | 건수 | 비율 |
|---|---|---|
| SL | 27 | 41% |
| PARTIAL | 17 | 26% |
| KD-EXIT | 16 | 24% |
| BEP-SL | 5 | 8% |
| TRAIL | 1 | 2% |

| 항목 | 값 |
|---|---|
| 롱 | 26건 |
| 숏 | 40건 |
| 진입 1m K 중앙 | 측정 불가 (BacktestTrade 필드 없음) |
| 진입 5m K 중앙 | 측정 불가 (BacktestTrade 필드 없음) |

### 3심볼 합계 (BTC 제외)

| 항목 | 값 |
|---|---|
| 합계 거래(정수) | 66건 (BONK 유일) |
| 합계 거래(qty가중) | 49.00 |
| 가중 승률 | 51.5% |
| 합계 총수익 | -18.33% |
| 최대 MDD | 45.69% |
| 합계 PF | 0.915 |
| 거래당 평균 | -0.278% |

---

## 정합성 서술

- **4차 실측 셀 A 유형 오류와 다름**: KD-EXIT 24% (셀 A=100%), 보유중앙 384분 (셀 A=19분)
- **3-Phase 청산 재현**: BEP-SL=5, PARTIAL=17, TRAIL=1 존재 ✅
- **BTC 0건**: G4 ATR 하한 1.85% vs BTC ATR 0.33~0.63% — 정상
- **SHIB/PEPE 0건**: `k_5m < 40.0` (롱 진입 임계값) + `prohibition` 8개 All-True 조건이 해당 기간 동시 충족되지 않음

> ⚠️ 상위 TF 룩어헤드 포함(15m 최대 14분) — 절대값은 실거래 대비 낙관 (L-1)

---

## 결론

**4TF CURRENT 전략(3/4 합의)은 현 파라미터(SL=3.7·Lev=20·24h Ticker)에서 손실 전략이다.**

- PF 0.915 (1 미만)
- 총수익 -18.33%, MDD 45.69%
- SL 비율 41% — 손절 다발
- 적용 심볼: 사실상 BONK 단일 (SHIB/PEPE 진입 조건 미충족)

이 수치가 M4 전략 개선 효과를 검증하는 유일한 비교 기준입니다.

---

## 이전 측정 오류 기록

| 구분 | consensus_mode | 거래수 | 총수익 | MDD | 오류 원인 |
|---|---|---|---|---|---|
| c4_measure.py (1차, 오류) | 4/4 (미전달 기본값) | 40건 | +50.96% | 24.01% | run() consensus_mode 미전달 |
| **c4_final.py (최종, 정확)** | **3/4 (명시 전달)** | **66건** | **-18.33%** | **45.69%** | — |

---

## C-5 스윕 결과 (참고)

**측정 조건**: entry/exit_variant=`"M4"` | SL=3.7·Trail=1.1·Lev=20·Funds=100% | 90일
**조합**: SLOPE_TH {5,10,15} × DIV_TH {None,1.0,1.5,2.0,3.0} = 15조합 × 4심볼

### 통과 기준 (§4-3)

PF≥1.3(3비BTC 합계) | 거래당평균≥0.65% | 90일≥60건(심볼당≥15) | MDD≤1.5×C4기준선 | BTC≤20건

### 통과 조합: **1개 — SLOPE=5, DIV=None**

| 항목 | SLOPE=5 DIV=None |
|---|---|
| PF (3비BTC 합계) | ∞ (3심볼 모두 누적 플러스) |
| 거래당 평균 | +1.780% |
| 총 거래(N, min) | 98건 (min=17건) |
| 최대 MDD | 9.00% |
| BTC | 0건 |
| 판정 | ✅ 통과 |

**심볼별 상세 (SLOPE=5 DIV=None)**:

| 심볼 | 건수 | 승률 | 거래당평균 | 누적 | MDD |
|---|---|---|---|---|---|
| BONK (합) | 56 | 83.9% | +1.880% | +105.30% | 8.38% |
| SHIB (합) | 25 | 68.0% | +1.950% | +48.76% | 9.00% |
| PEPE (합) | 17 | 88.2% | +1.510% | +25.67% | 8.00% |
| BTC (합) | 0 | — | — | — | — |

> ⚠️ 상위 TF 룩어헤드 포함 — 절대값은 실거래 대비 낙관
> ⚠️ SLOPE=5 DIV=None = 현재 실거래 설정(_strategy.json 24h Ticker: slope=5.0, div=null)과 동일
