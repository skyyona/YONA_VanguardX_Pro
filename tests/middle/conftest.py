"""
tests/middle/conftest.py
중단 테스트 공용 — 각 테스트 종료 직후 메인 스레드에서 가비지 수집 (2026-11-17).

Tk 화면 테스트가 만든 StringVar·위젯은 패널 객체와 순환 참조로 남아, 다음 가비지 수집 때 정리된다.
그 수집이 다른 테스트의 작업 스레드(STAGE·상세 갱신 스레드풀, Pending 조회 스레드)에서 일어나면
Tk 변수가 잘못된 스레드에서 지워져 'PytestUnraisableExceptionWarning'(Variable.__del__) 경고가 나거나,
최악에는 'Tcl_AsyncDelete: async handler deleted by the wrong thread'로 테스트 프로세스가 강제 종료된다
(재현: 같은 날 scratch 실험 — 작업 스레드 GC 시 종료 코드 3, 메인 스레드 선정리 20회 오류 0).
테스트 코드만 해당 — 앱은 창이 종료 시까지 유지되어 이 순서 문제가 없다.
"""
import gc

import pytest


@pytest.fixture(autouse=True)
def _collect_tk_leftovers_on_main_thread():
    yield
    gc.collect()   # 테스트가 남긴 Tk 객체를 메인 스레드에서 정리 — 이후 작업 스레드에서 지워지지 않게
