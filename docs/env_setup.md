# YONA VanguardX Pro — .env 파일 설정 가이드

이 문서는 세 모듈의 `.env` 파일 위치·키 이름·Binance API 권한 설정을 기록합니다.  
**실제 API 키·시크릿 값은 절대 이 파일에 기록하지 않습니다.**

---

## 모듈별 .env 파일 위치 및 키 이름

| 모듈 | .env 경로 | API 키 변수명 | API 시크릿 변수명 |
|---|---|---|---|
| 상단 (header) | `header/.env` | `HEADER_BINANCE_API_KEY` | `HEADER_BINANCE_API_SECRET` |
| 중단 (middle) | `middle/.env` | `MIDDLE_BINANCE_API_KEY` | — (시크릿 불필요, 공개 API 전용) |
| 하단 (bottom_engine) | `bottom_engine/.env` | `BOTTOM_BINANCE_API_KEY` | `BOTTOM_BINANCE_API_SECRET` |

> 세 모듈은 **각자 별도의 `.env` 파일과 접두어를 사용합니다.**  
> 키 이름을 혼동하면 조용히 빈 문자열로 읽혀 "API 키 미설정" 오류가 발생합니다.

---

## .env 파일 작성 형식

```
HEADER_BINANCE_API_KEY=여기에_API_키_입력
HEADER_BINANCE_API_SECRET=여기에_시크릿_입력
```

- 값에 인용부호(`"` 또는 `'`)를 붙이지 않습니다. 붙이면 자동 제거됩니다.
- 파일 인코딩은 **UTF-8 (BOM 없음)** 권장. UTF-8 BOM이 있어도 자동 처리됩니다.
- `.env` 파일은 `.gitignore`에 등재되어 있어 Git에 커밋되지 않습니다.

---

## Binance API 키 권한 설정

### 상단 모듈 (`HEADER_BINANCE_API_KEY`)

| 권한 | 설정 |
|---|---|
| 읽기 (Enable Reading) | ✅ 활성화 필수 |
| USDⓈ-M Futures 사용 (Enable Futures) | ✅ 활성화 필수 |
| 범용 전송 허용 (Enable Universal Transfer) | ✅ 활성화 필수 (Spot ↔ Futures 이체) |
| IP 제한 | 고정 IP 등록 권장 — IP 무제한 설정 시 바이낸스 보안 정책에 의해 키 자동 삭제 위험 |

> **주의**: IP 무제한 + Futures 외 권한 활성화 조합은 바이낸스 보안 정책에 의해  
> 키가 자동 삭제될 수 있습니다. 반드시 고정 IP를 등록하세요.

### 하단 모듈 (`BOTTOM_BINANCE_API_KEY`)

| 권한 | 설정 |
|---|---|
| 읽기 (Enable Reading) | ✅ 활성화 필수 |
| USDⓈ-M Futures 사용 (Enable Futures) | ✅ 활성화 필수 |
| IP 제한 | 고정 IP 등록 권장 |

### 중단 모듈 (`MIDDLE_BINANCE_API_KEY`)

공개 API 전용 — API 키는 사용량 추적 목적으로만 사용됩니다. 키가 없어도 동작합니다.

---

## 앱 재시작 필요 시점

`HeaderBinanceClient`는 앱 시작 시 `.env`를 1회 읽습니다.  
`.env` 파일을 수정한 경우 **앱을 재시작해야** 새 키가 적용됩니다.

---

## 로그 확인

앱 실행 중 API 통신 오류는 `logs/app.log`에 기록됩니다.

```
# 예시: 타임스탬프 오차(-1021)
2026-10-17 14:32:01,234 WARNING header.api.binance_client _signed_get ...: HTTP 400 {"code":-1021,...}

# 예시: 잘못된 서명(-1022)
2026-10-17 14:32:01,234 WARNING header.api.binance_client _signed_get ...: HTTP 400 {"code":-1022,...}

# 예시: IP 미등록(-2015)
2026-10-17 14:32:01,234 WARNING header.api.binance_client _signed_get ...: HTTP 403 {"code":-2015,...}
```

로그에 `-1021` → 로컬 시계 오차: `w32tm /resync` 실행  
로그에 `-1022` → 시크릿 오류: `.env` 파일 값 확인  
로그에 `-2015` → IP 미등록: Binance API 관리 페이지에서 IP 추가
