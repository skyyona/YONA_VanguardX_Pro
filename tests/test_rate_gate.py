"""
tests/test_rate_gate.py
바이낸스 REST 429/418 공통 차단 장치 (core/rate_gate.py, 2026-11-15) — 네트워크 없이 대역 응답·가짜 시계.
 - 차단 중 네트워크로 보내지 않음 · 429/418 Retry-After 차단 (없으면 60·300초) · 원래 HTTPError 그대로
 - 차단 기록 파일로 재시작·다른 프로세스 이어받음 · 바이낸스 외 주소 통과 · 실패 문구 · 로그 제외 · 사용량 기록
"""
import http.client
import io
import logging
import urllib.error
import urllib.request

import pytest

import core.rate_gate as rg

B = "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT"


class _Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _http_error(code, retry_after=None):
    h = http.client.HTTPMessage()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(B, code, "err", h, io.BytesIO(b'{"code":-1003}'))


class _Resp:
    def __init__(self, weight="321"):
        self.headers = http.client.HTTPMessage()
        if weight:
            self.headers["X-MBX-USED-WEIGHT-1M"] = weight


def _gate(tmp_path, clock=None, responses=None):
    calls = []
    responses = list(responses or [])

    def orig(url, *a, **k):
        calls.append(url.full_url if isinstance(url, urllib.request.Request) else url)
        r = responses.pop(0) if responses else _Resp()
        if isinstance(r, Exception):
            raise r
        return r
    g = rg.RateGate(tmp_path / "rate_gate.json", clock or _Clock())
    return g, g.wrap(orig), calls


def test_429_blocks_for_retry_after_without_network(tmp_path):
    clk = _Clock()
    g, op, calls = _gate(tmp_path, clk, [_http_error(429, 42)])
    with pytest.raises(urllib.error.HTTPError) as ei:
        op(B)
    assert ei.value.code == 429                                   # 원래 오류 그대로 (기존 처리 유지)
    with pytest.raises(rg.RateGateBlocked) as bi:
        op(urllib.request.Request(B))                             # Request 객체도 대상
    msg = str(bi.value)
    assert "Rate Limited" in msg and "URLError" not in msg and "timed out" not in msg
    assert "503" not in msg and "-1008" not in msg
    assert len(calls) == 1                                        # 차단 중 네트워크 미전송
    clk.t += 41
    assert g.remaining() == pytest.approx(1.0)
    clk.t += 1.01
    op(B)                                                         # 해제 후 정상
    assert len(calls) == 2


@pytest.mark.parametrize("code, default", [(429, 60), (418, 300)])
def test_default_duration_without_retry_after(tmp_path, code, default):
    clk = _Clock()
    g, op, _ = _gate(tmp_path, clk, [_http_error(code)])
    with pytest.raises(urllib.error.HTTPError):
        op(B)
    assert g.remaining() == pytest.approx(default)


def test_418_uses_retry_after_and_never_shortens(tmp_path):
    clk = _Clock()
    g, op, _ = _gate(tmp_path, clk, [_http_error(418, 705), _http_error(429, 10)])
    with pytest.raises(urllib.error.HTTPError):
        op(B)
    assert g.remaining() == pytest.approx(705)                    # 11-13 실제 응답 Retry-After 705
    g._block(429, "10")                                           # 더 짧은 차단은 기존 해제 시각을 줄이지 않음
    assert g.remaining() == pytest.approx(705)


def test_block_persists_to_file_for_restart_and_other_process(tmp_path):
    clk = _Clock()
    g, op, _ = _gate(tmp_path, clk, [_http_error(418, 600)])
    with pytest.raises(urllib.error.HTTPError):
        op(B)
    g2, op2, calls2 = _gate(tmp_path, clk)                        # 앱 재시작 / 오프라인 스크립트
    assert g2.remaining() == pytest.approx(600)
    with pytest.raises(rg.RateGateBlocked):
        op2(B)
    assert calls2 == []


def test_running_process_picks_up_block_written_by_another(tmp_path):
    clk = _Clock()
    g, op, calls = _gate(tmp_path, clk)
    op(B)
    other = rg.RateGate(tmp_path / "rate_gate.json", clk)
    other._block(418, "120")                                      # 다른 프로세스가 차단 기록
    clk.t += rg._FILE_RECHECK_SEC
    with pytest.raises(rg.RateGateBlocked):
        op(B)
    assert len(calls) == 1


def test_non_binance_and_other_errors_pass_through(tmp_path):
    g, op, calls = _gate(tmp_path, responses=[_http_error(429, 30), _Resp()])
    with pytest.raises(urllib.error.HTTPError):
        op(B)
    op("https://example.com/x")                                   # 바이낸스 외 주소는 차단 중에도 통과
    assert calls[-1] == "https://example.com/x"
    g2, op2, _ = _gate(tmp_path / "b", responses=[_http_error(400)])
    with pytest.raises(urllib.error.HTTPError):
        op2(B)
    assert g2.remaining() == 0                                    # 400 등은 차단하지 않음


def test_success_records_used_weight(tmp_path):
    g, op, _ = _gate(tmp_path, responses=[_Resp("1501")])
    op(B)
    assert g.last_weight[0] == 1501


def test_log_filter_drops_blocked_messages_only():
    f = rg._DropBlockedLogs()
    rec = lambda m: logging.LogRecord("x", logging.WARNING, __file__, 1, m, None, None)
    assert f.filter(rec(f"middle _get {rg.MARK} — ... | https://fapi.binance.com/x")) is False
    assert f.filter(rec("middle _get HTTP 429 ...")) is True


def test_install_once_and_not_on_import(monkeypatch, tmp_path):
    sentinel = lambda *a, **k: _Resp()
    monkeypatch.setattr(urllib.request, "urlopen", sentinel)
    assert urllib.request.urlopen is sentinel                     # 불러오기만으로는 연결 안 됨
    root = logging.getLogger()
    before = list(root.filters)
    try:
        g1 = rg.install(tmp_path / "s.json")
        wrapped = urllib.request.urlopen
        assert wrapped is not sentinel and wrapped._rate_gate is g1
        assert rg.install(tmp_path / "s.json") is g1 and urllib.request.urlopen is wrapped   # 두 번째 호출은 그대로
    finally:
        root.filters[:] = before
        for h in root.handlers:
            h.filters[:] = [x for x in h.filters if not isinstance(x, rg._DropBlockedLogs)]
        monkeypatch.setattr(rg, "_gate", None)


def test_wait_if_blocked_for_offline_scripts(monkeypatch, tmp_path):
    """3단계: 오프라인 스크립트는 차단 기록(앱이 남긴 것 포함)이 있으면 요청하지 않고 해제까지 대기."""
    clk = _Clock()
    other = rg.RateGate(tmp_path / "rate_gate.json", clk)
    other._block(418, "90")                                       # 앱(다른 프로세스)이 남긴 차단 기록
    g = rg.RateGate(tmp_path / "rate_gate.json", clk)
    monkeypatch.setattr(rg, "_gate", g)
    slept, logs = [], []
    def sleep(s):
        slept.append(s); clk.t += s
    assert rg.wait_if_blocked(log=logs.append, sleep=sleep) == pytest.approx(91)
    assert slept == [pytest.approx(91)] and "대기" in logs[0]
    assert rg.wait_if_blocked(log=logs.append, sleep=sleep) == 0  # 해제 후 바로 반환


def test_scripts_install_gate_in_entry_point_only():
    """3단계: 오프라인 스크립트는 실행 진입점에서 install (불러오기만으로는 설치 안 됨 — 테스트 영향 없음)."""
    import pathlib
    root = pathlib.Path(rg.__file__).resolve().parents[1]
    for name in ("forecast_train.py", "forecast_evaluate.py", "build_backtest_cache.py", "main.py"):
        src = (root / name).read_text(encoding="utf-8")
        entry = src[src.index('if __name__ == "__main__":'):]
        assert "rate_gate.install()" in entry, name
        assert src.count("rate_gate.install()") == 1, name
