"""
tests/header/test_update_timer.py
헤더 UpdateTimer — 주기마다 새 스레드를 만들지 않고 상주 스레드 1개에서 반복 (2026-11-05 Event 핸들 증가 대응)
"""
import threading
import time

from header.status.update_timer import UpdateTimer


def _wait_for(cond, limit=3.0):
    end = time.time() + limit
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


def test_repeats_on_single_thread():
    idents = []
    t = UpdateTimer(0.02, lambda: idents.append(threading.get_ident()))
    t.start()
    assert _wait_for(lambda: len(idents) >= 5)
    t.stop()
    assert len(set(idents)) == 1                    # 기존: 주기마다 다른 스레드
    assert idents[0] != threading.get_ident()       # 호출 스레드가 아닌 작업 스레드


def test_first_call_after_interval():
    calls = []
    t = UpdateTimer(0.3, lambda: calls.append(time.time()))
    t0 = time.time()
    t.start()
    assert _wait_for(lambda: calls)
    t.stop()
    assert calls[0] - t0 >= 0.29                    # 기존과 같이 시작 즉시가 아닌 interval 후 첫 호출


def test_stop_halts_callbacks():
    calls = []
    t = UpdateTimer(0.02, lambda: calls.append(1))
    t.start()
    assert _wait_for(lambda: len(calls) >= 2)
    t.stop()
    time.sleep(0.05)
    n = len(calls)
    time.sleep(0.15)
    assert len(calls) == n


def test_double_start_keeps_one_thread():
    idents = []
    t = UpdateTimer(0.02, lambda: idents.append(threading.get_ident()))
    t.start()
    t.start()
    assert _wait_for(lambda: len(idents) >= 6)
    t.stop()
    assert len(set(idents)) == 1


def test_restart_after_stop_during_callback_runs_single_loop():
    """콜백 실행 중 stop → 즉시 start 해도 이전 스레드는 종료, 새 스레드 1개만 반복."""
    gate = threading.Event()
    idents = []
    def cb():
        idents.append(threading.get_ident())
        if len(idents) == 1:
            gate.wait(1.0)                          # 첫 콜백을 붙잡은 채 stop/start
    t = UpdateTimer(0.02, cb)
    t.start()
    assert _wait_for(lambda: idents)
    t.stop()
    t.start()
    gate.set()
    assert _wait_for(lambda: len(idents) >= 6)
    t.stop()
    first, rest = idents[0], idents[1:]
    assert len(set(rest)) == 1 and rest[0] != first


def test_callback_exception_does_not_stop_loop():
    calls = []
    def cb():
        calls.append(1)
        raise RuntimeError("x")
    t = UpdateTimer(0.02, cb)
    t.start()
    assert _wait_for(lambda: len(calls) >= 3)
    t.stop()
