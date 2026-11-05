"""
tests/test_instance_lock.py
단일 실행 락 — Windows 이름 있는 뮤텍스 (2026-11-05, PID 파일 방식 '중복 실행' 오판 대체)
실제 별도 프로세스로 검증. 실행 중인 앱과 겹치지 않도록 테스트 전용 뮤텍스 이름 사용.
"""
import os
import subprocess
import sys
import time
import uuid

import pytest

import main

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 자식 프로세스: 테스트 이름으로 락 획득 → 결과 출력 → (hold면) 종료 신호까지 보유
_CHILD = r"""
import sys, time
import main
main._MUTEX_NAME = sys.argv[1]
import tkinter.messagebox as _mb
_mb.showerror = lambda *a, **k: print("DUP_DIALOG", flush=True)
try:
    main._acquire_instance_lock()
except SystemExit as e:
    print("EXIT", e.code, flush=True)
    sys.exit(0)
print("ACQUIRED", flush=True)
if sys.argv[2] == "hold":
    import os
    print(os.getpid(), flush=True)   # 실제 보유 프로세스 (venv python.exe는 실행기 → 이 프로세스는 그 자식)
    sys.stdin.readline()
"""


def _child(name, mode="once"):
    return subprocess.Popen([sys.executable, "-c", _CHILD, name, mode], cwd=_ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def _start_holder(name):
    holder = _child(name, "hold")
    assert holder.stdout.readline().strip() == "ACQUIRED"
    return holder, int(holder.stdout.readline())


def _force_kill_tree(p):
    """실행기+실제 프로세스 트리 강제 종료 (작업 관리자 앱 그룹 '작업 끝내기'와 같은 TerminateProcess)."""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    p.wait(timeout=30)


def _run_child(name):
    p = _child(name)
    out, _ = p.communicate(timeout=120)
    return out.split()


@pytest.fixture()
def name(monkeypatch):
    n = f"Local\\YONA_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(main, "_MUTEX_NAME", n)
    yield n
    main._release_instance_lock()


def test_second_instance_blocked_while_first_holds(name):
    main._acquire_instance_lock()
    assert main._instance_mutex
    assert _run_child(name) == ["DUP_DIALOG", "EXIT", "0"]


def test_allowed_after_normal_release(name):
    main._acquire_instance_lock()
    main._release_instance_lock()
    assert main._instance_mutex is None
    assert _run_child(name) == ["ACQUIRED"]


def test_allowed_right_after_forced_kill(name):
    """보유 프로세스 강제 종료(작업 관리자 '작업 끝내기'·Stop-Process와 같은 TerminateProcess) 직후 바로 실행 허용."""
    holder, _ = _start_holder(name)
    assert _run_child(name) == ["DUP_DIALOG", "EXIT", "0"]   # 보유 중에는 차단
    _force_kill_tree(holder)
    t0 = time.time()
    main._acquire_instance_lock()
    assert main._instance_mutex                             # 남은 파일·PID 판정 없이 즉시 허용
    assert time.time() - t0 < 1.0


def test_exited_process_handle_held_elsewhere_does_not_block(name):
    """종료된 보유 프로세스의 객체를 다른 프로세스가 붙잡고 있어도(오늘 PcaSvc 사례) 차단하지 않음."""
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    holder, real_pid = _start_holder(name)
    proc_handle = k32.OpenProcess(0x0400, False, real_pid)   # 이 테스트가 실제 보유 프로세스 객체를 붙잡음
    assert proc_handle
    try:
        _force_kill_tree(holder)
        old_check = k32.OpenProcess(0x0400, False, real_pid)  # 기존 PID 방식이었다면 '살아 있음' 오판
        assert old_check
        k32.CloseHandle(ctypes.c_void_p(old_check))
        main._acquire_instance_lock()
        assert main._instance_mutex
    finally:
        k32.CloseHandle(ctypes.c_void_p(proc_handle))
