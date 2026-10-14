# M4 Stoch RSI div 기준선 — 150심볼 × 180일 (SL=2.8%)

측정일: 2026-10-13  
커밋 기준: `448c3d7`

---

## §1 측정 배경

`docs/baseline_m4_150sym_180d.md` (커밋 기준 `7df1136`, SL=1.8%)는 두 가지 이유로 교체:

1. **파라미터 변경**: SL 1.8%→2.8%, trail 0.7%→1.2%, leverage 10→20.  
   사용자 설정 변경 (e236151, bec14f2, 16882ef). 해당 값의 사전 측정 기록 없음.
2. **실거래 파라미터 자동 동기화 구현** (`d50ecfa`):  
   `base_params.py`가 `_strategy.json "24h Ticker"`를 직접 읽도록 변경.  
   이후 기준선은 반드시 현행 `_strategy.json` 파라미터로 재측정해야 유효.

---

## §2 측정 조건

| 항목 | 값 |
|------|-----|
| entry_variant | `"M4"` |
| exit_variant | `"CURRENT"` |
| 기간 | 180일 |
| 심볼 수 | 150개 (`selected_symbols.json`) |
| leverage | 20 |
| stop_loss | 2.8% |
| trail_stop | 1.2% |
| use_macro | false |
| sort_mode | 24h Ticker |
| m4_rsi_vol_mult | 1.5 |
| G1 신호 | Stoch RSI 다이버전스 (tf5.div == "bull"/"bear") |
| 소요 시간 | 11.0분 |

---

## §3 전체 집계

| 항목 | 값 |
|------|-----|
| 전체 거래 건수 | **368건** |
| 일평균 | 2.04건/일 |
| 가중 승률 | 70.1% |
| **기대값(R)** | **-0.0220R** |
| PF | 0.913 ±0.095 |
| 1R | 8.00% |

---

## §4 청산 사유 분포

| 사유 | 건수 | 비율 | WR% | 평균pnl% | 평균R |
|------|------|------|-----|---------|------|
| KD-EXIT | 265 | 72.0% | 92.8% | +1.999% | +0.250R |
| SL | 89 | 24.2% | 0.0% | -8.295% | **-1.037R** |
| PARTIAL | 6 | 1.6% | 100.0% | +11.707% | +1.463R |
| TRAIL | 6 | 1.6% | 100.0% | +12.391% | +1.549R |
| BEP-SL | 2 | 0.5% | 0.0% | -0.290% | -0.036R |

| 구분 | 건수 | 비율 |
|------|------|------|
| Phase3 도달 (PARTIAL+TRAIL) | 12건 | 3.3% |
| 조기 청산 (KD-EXIT) | 265건 | 72.0% |
| SL 청산 | 89건 | 24.2% |
| BEP-SL 청산 | 2건 | 0.5% |

---

## §5 롱/숏 분리

| 방향 | N | WR | EV(R) | PF |
|------|---|----|----|---|
| **Long** | 174건 | 71.8% | **+0.0215R** | 1.092 |
| **Short** | 194건 | 68.6% | **-0.0609R** | 0.773 |

거래 발생 심볼: **41 / 150**  
PF>1 심볼: **16 / 41**

---

## §6 EV 음수 원인 분석

| 항목 | 계산 | R 합계 |
|------|------|--------|
| KD-EXIT 기여 | 265건 × +0.250R | **+66.3R** |
| SL 기여 | 89건 × -1.037R | **-92.3R** |
| PARTIAL 기여 | 6건 × +1.463R | +8.8R |
| TRAIL 기여 | 6건 × +1.549R | +9.3R |
| BEP-SL 기여 | 2건 × -0.036R | -0.1R |
| **합계** | 368건 | **-8.1R / 368 = -0.0220R** |

---

## §7 구 기준선 비교

| 항목 | 구 기준선 (SL=1.8%, lev=10) | **신 기준선 (SL=2.8%, lev=20)** |
|------|--------------------------|----------------------------------|
| 커밋 | `7df1136` | `448c3d7` |
| 기간 | 180일 | 180일 |
| N | 1,216건 | **368건** |
| WR | 51.7% | **70.1%** |
| SL 비율 | 15.9% | **24.2%** |
| SL 평균R | -4.694R (1R 정의 정정 eb13e71 이전 단위 — 직접 비교 불가) | **-1.037R** |
| EV | -0.3437R (1R 정의 정정 eb13e71 이전 단위 — 직접 비교 불가) | **-0.0220R** |
| PF | 0.695 | **0.913** |

단위 무관 지표(PF·WR·N)만 직접 비교 가능.

---

## §8 측정 도구

스크립트: `exit_reason_analysis.py` (PERIOD="180일", `_strategy.json` 자동 읽기)  
캐시: `backtest_cache/180일/` (150심볼)  
결과 파일: `exit_reason_analysis_result.json`

---

## §9 판정

| 기준 | 값 | 판정 |
|---|---|---|
| N ≥ 50 | 368 | 통과 |
| EV > 0 | −0.0220R | 미달 |
| PF > 1 | 0.913 (± 0.095 → 0.818~1.008) | 미달 (구간에 1 포함) |
| PF>1 심볼 ≥ 50% | 16/41 = 39.0% | 미달 |

---

## §10 측정 메타

| 항목 | 값 |
|---|---|
| commit | `448c3d7` |
| dirty | **True** (측정 시 미추적 파일 존재 — `exit_reason_live_180d_log.txt` 리다이렉트 생성) |
| run_at | 2026-10-13T23:28:58 |
| period | 180일 |
| symbols_count | 150 |
| sort_mode | 24h Ticker |
| leverage | 20 |
| stop_loss | 2.8 |
| trail_stop | 1.2 |
| use_macro | false |
| m4_rsi_vol_mult | 1.5 |
| mmr | 0.004 |
| funds_pct | 100 |
| phase1_timeout_bars | 0 |
| prohibition.common_liq | true |
| prohibition.common_fr | true |
| prohibition.common_new | true |
| prohibition.common_hunter | true |
| prohibition.long_fomo | true |
| prohibition.long_short_open | true |
| prohibition.short_accum | true |
| prohibition.short_long_open | true |
