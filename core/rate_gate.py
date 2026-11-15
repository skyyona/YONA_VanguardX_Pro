"""
core/rate_gate.py
바이낸스 REST 429/418 공통 차단 장치 — 앱 전체(중단·하단·헤더·앱 안 백테스트 로더)와 오프라인 스크립트 공용.

배경 (2026-11-13): 429를 받은 뒤에도 요청을 계속 보내 418(IP 차단)로 넘어갔고, 차단 중 요청이 이어져
차단이 약 24분으로 늘어났다. 바이낸스는 429 뒤에 물러서지 않으면 차단하고, 반복하면 2분~3일로 늘린다.

동작: install()이 urllib.request.urlopen을 감싼다 (프로젝트의 모든 REST가 이 함수를 쓴다 — 2026-11-15 전수 확인).
  - 바이낸스 주소 요청만 대상. 차단 중이면 네트워크로 보내지 않고 RateGateBlocked를 즉시 발생.
    문구에 'Rate Limited' 포함(엔진 진입 재시도 제외 조건), 'URLError'·'timed out'·'503'·'-1008' 미포함
    (엔진이 그 문구를 보면 포지션 확인 후 재주문 경로로 감).
  - 응답 429/418 → Retry-After(초)까지 차단 (헤더 없으면 429 60초 · 418 300초). 원래 HTTPError는 그대로 다시 발생.
  - 차단 해제 시각을 data/rate_gate.json에 저장 → 앱 재시작·다른 프로세스(오프라인 스크립트)도 이어받음.
  - 차단 중 클라이언트들이 남기는 같은 경고는 로그에서 제외 (장치가 차단 시작·연장 때 한 번 남김).
  - 정상 응답의 IP 사용량(X-MBX-USED-WEIGHT-1M) 기록.
불러오기만으로는 연결되지 않는다 — 실행 진입점(main.py·스크립트)에서 install() 1회 (테스트가 urlopen을 대역으로 바꿔 씀).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "rate_gate.json"
_HOSTS = ("fapi.binance.com", "api.binance.com")
_DEFAULT_SEC = {429: 60, 418: 300}
_FILE_RECHECK_SEC = 5.0             # 다른 프로세스가 남긴 차단 기록 재확인 간격
MARK = "Rate Limited (공통 차단)"    # RateGateBlocked 문구 표지 — 로그 제외 필터가 사용


class RateGateBlocked(Exception):
    """차단 중 요청 — 네트워크로 보내지 않음."""


class RateGate:
    def __init__(self, state_path: Path = STATE_PATH, clock=time.time) -> None:
        self._path = state_path
        self._clock = clock
        self._lock = threading.Lock()
        self._until = 0.0
        self._code = 0
        self._file_checked = -1e18
        self.last_weight: tuple[int, float] | None = None   # (사용량, 시각)
        self._load()

    # ── 상태 ─────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            until, code = float(d.get("blocked_until", 0)), int(d.get("code", 0))
        except (OSError, ValueError, TypeError):
            return
        if until > self._until:
            self._until, self._code = until, code

    def remaining(self) -> float:
        """남은 차단 초 (0이면 차단 아님). 다른 프로세스의 기록도 _FILE_RECHECK_SEC마다 확인."""
        now = self._clock()
        with self._lock:
            if now - self._file_checked >= _FILE_RECHECK_SEC:
                self._file_checked = now
                self._load()
            return max(0.0, self._until - now)

    def _block(self, code: int, retry_after: str | None) -> None:
        try:
            sec = max(1.0, float(retry_after)) if retry_after is not None else float(_DEFAULT_SEC[code])
        except ValueError:
            sec = float(_DEFAULT_SEC[code])
        now = self._clock()
        with self._lock:
            until = max(self._until, now + sec)
            extended = until > self._until
            self._until, self._code = until, code
            if extended:
                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    self._path.write_text(json.dumps({"blocked_until": until, "code": code, "set_at": now}),
                                          encoding="utf-8")
                except OSError as e:
                    logging.warning("rate_gate: 차단 기록 저장 실패 %s", e)
        if extended:
            logging.warning("rate_gate: 바이낸스 HTTP %d — 요청 차단 %.0f초 (Retry-After %s)", code, sec, retry_after)

    # ── 감싸기 ───────────────────────────────────────────────
    def wrap(self, orig):
        def urlopen(url, *args, **kwargs):
            target = url.full_url if isinstance(url, urllib.request.Request) else str(url)
            if not any(h in target for h in _HOSTS):
                return orig(url, *args, **kwargs)
            rem = self.remaining()
            if rem > 0:
                raise RateGateBlocked(f"{MARK} — 바이낸스 HTTP {self._code} 이후 요청 중단, {int(rem) + 1}초 남음")
            try:
                resp = orig(url, *args, **kwargs)
            except urllib.error.HTTPError as e:
                if e.code in _DEFAULT_SEC:
                    self._block(e.code, e.headers.get("Retry-After") if e.headers else None)
                raise
            headers = getattr(resp, "headers", None)
            w = headers.get("X-MBX-USED-WEIGHT-1M") if headers is not None else None
            if w:
                try:
                    self.last_weight = (int(w), self._clock())
                except ValueError:
                    pass
            return resp
        urlopen._rate_gate = self   # 중복 연결 방지 표지
        return urlopen


class _DropBlockedLogs(logging.Filter):
    """차단 중 각 클라이언트가 남기는 RateGateBlocked 경고는 제외 (차단 시작·연장은 rate_gate가 한 번 기록)."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return MARK not in record.getMessage()
        except Exception:
            return True


_gate: RateGate | None = None


def install(state_path: Path = STATE_PATH) -> RateGate:
    """urllib.request.urlopen을 공통 차단 장치로 감싸고 로그 필터를 붙인다 (여러 번 불러도 1회만)."""
    global _gate
    cur = urllib.request.urlopen
    if getattr(cur, "_rate_gate", None) is not None:
        return cur._rate_gate
    _gate = RateGate(state_path)
    urllib.request.urlopen = _gate.wrap(cur)
    flt = _DropBlockedLogs()
    root = logging.getLogger()
    root.addFilter(flt)
    for h in root.handlers:
        h.addFilter(flt)
    return _gate


def remaining() -> float:
    """설치된 차단 장치의 남은 차단 초 (설치 전이면 0)."""
    return _gate.remaining() if _gate is not None else 0.0


def wait_if_blocked(log=print, sleep=time.sleep) -> float:
    """오프라인 스크립트용 — 차단 중이면 해제될 때까지 기다린 뒤 돌아온다. 기다린 초 반환 (요청은 보내지 않음)."""
    waited = 0.0
    rem = remaining()
    while rem > 0:
        log(f"  바이낸스 요청 차단 중 — {int(rem) + 1}초 대기 (rate_gate)")
        sleep(rem + 1)
        waited += rem + 1
        rem = remaining()
    return waited
