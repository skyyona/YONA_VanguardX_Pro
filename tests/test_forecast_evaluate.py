"""
tests/test_forecast_evaluate.py
4단계 실사용 채점(forecast_evaluate.py): 사건 12h 중복 제외 · 통과/탈락/검증 중(연장) 판정 · --apply 시에만 판정식 파일 갱신.
가격 경로 조회(_path)만 대역.
"""
import json

import forecast_evaluate as fe
from middle.analysis.forecast import STEP_MS

H12 = 144 * STEP_MS
DAY = 86_400_000
T0 = 1_790_000_000_000 // STEP_MS * STEP_MS


def _setup(monkeypatch, tmp_path, rows, path_fn, adopted=("down",)):
    log = tmp_path / "forecast_log.csv"
    with open(log, "w", encoding="utf-8") as f:
        f.write("t_close,symbol,context,price,r24,score_dn,score_up,score_big,labels,shown\n")
        for t, s, r24, labels in rows:
            f.write(f"{t},{s},all,1.0,{r24},0,0,0,{labels},{labels}\n")
    params = {"trained_at": "x", "labels": [
        {"key": k, "context": "all", "model": "dn", "r24_range": [-1e9, 15], "direction": "S", "adopted": k in adopted,
         "live_status": "검증 중"} for k in ("down",)]}
    pp = tmp_path / "forecast_params.json"
    pp.write_text(json.dumps(params), encoding="utf-8")
    monkeypatch.setattr(fe, "LOG", log)
    monkeypatch.setattr(fe, "PARAMS_PATH", pp)
    monkeypatch.setattr(fe, "EVIDENCE", tmp_path)
    monkeypatch.setattr(fe, "_path", path_fn)
    return pp


def _rows(n_events, days):
    """사건 n_events (종목 다름·하루 간격으로 분산) + 각 시점 기준 표본(표시 없음) 3행."""
    out = []
    for k in range(n_events):
        t = T0 + (k % days) * DAY + (k // days) * STEP_MS * 3
        out.append((t, f"E{k}USDT", 3.0, "down"))
        out += [(t, f"B{k}_{j}USDT", 3.0, "") for j in range(3)]
    return out


def test_pass_when_criteria_met_and_apply_updates_file(monkeypatch, tmp_path):
    # 사건: 12h −6% (숏 적중), 기준 표본: +1%
    pp = _setup(monkeypatch, tmp_path, _rows(70, 28),
                lambda s, t: (-6.0 - (hash(s) % 7) * 0.1, -7.0, 1.0) if s.startswith("E") else (1.0, -1.0, 2.0))
    fe.main(apply=False)
    assert json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_status"] == "검증 중"   # 미적용
    fe.main(apply=True)
    lab = json.loads(pp.read_text(encoding="utf-8"))["labels"][0]
    assert lab["live_status"] == "통과" and lab["live_test"]["events"] == 70


def test_fail_when_direction_wrong(monkeypatch, tmp_path):
    pp = _setup(monkeypatch, tmp_path, _rows(70, 28),
                lambda s, t: (6.0, -1.0, 7.0) if s.startswith("E") else (-6.0 if hash(s) % 3 == 0 else 1.0, -7.0, 1.0))
    fe.main(apply=True)
    assert json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_status"] == "탈락"


def test_too_few_events_extends_then_fails_after_8_weeks(monkeypatch, tmp_path):
    path = lambda s, t: (-6.0, -7.0, 1.0) if s.startswith("E") else (1.0, -1.0, 2.0)
    pp = _setup(monkeypatch, tmp_path, _rows(20, 20), path)
    fe.main(apply=True)
    assert json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_status"] == "검증 중"
    rows = _rows(20, 20) + [(T0 + 57 * DAY, "LATEUSDT", 3.0, "")]          # 기록 기간 8주 초과
    pp = _setup(monkeypatch, tmp_path, rows, path)
    fe.main(apply=True)
    assert json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_status"] == "탈락"


def test_other_context_rows_are_ignored(monkeypatch, tmp_path):
    rows = [(t, s, r24, lab) for t, s, r24, lab in _rows(70, 28)]
    pp = _setup(monkeypatch, tmp_path, rows, lambda s, t: (-6.0, -7.0, 1.0) if s.startswith("E") else (1.0, -1.0, 2.0))
    log = tmp_path / "forecast_log.csv"
    log.write_text(log.read_text(encoding="utf-8").replace(",all,", ",list,"), encoding="utf-8")   # 전부 목록 조건 기록
    fe.main(apply=True)
    lab = json.loads(pp.read_text(encoding="utf-8"))["labels"][0]
    assert lab["live_test"]["events"] == 0 and lab["live_status"] == "검증 중"


def test_duplicate_rows_counted_once(monkeypatch, tmp_path):
    """C: 같은 판정 시점·종목 중복 행(2026-11-10 시작 직후 93행)은 한 번만 — 결과가 중복 없는 기록과 같음."""
    path = lambda s, t: (-6.0 - (hash(s) % 7) * 0.1, -7.0, 1.0) if s.startswith("E") else (1.0, -1.0, 2.0)
    pp = _setup(monkeypatch, tmp_path, _rows(70, 28), path)
    fe.main(apply=True)
    once = json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_test"]
    pp = _setup(monkeypatch, tmp_path, _rows(70, 28) * 2, path)            # 모든 행 두 번
    fe.main(apply=True)
    twice = json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_test"]
    assert twice["events"] == once["events"] == 70 and twice["base_samples"] == once["base_samples"]


def test_repeated_signal_within_12h_counts_once(monkeypatch, tmp_path):
    rows = [(T0 + k * STEP_MS * 3, "AUSDT", 3.0, "down") for k in range(10)]        # 같은 종목 30분 간격 10번
    rows += [(T0 + H12 + k * STEP_MS * 3, "AUSDT", 3.0, "down") for k in range(2)]   # 12h 뒤 다시
    pp = _setup(monkeypatch, tmp_path, rows, lambda s, t: (-6.0, -7.0, 1.0))
    fe.main(apply=True)
    assert json.loads(pp.read_text(encoding="utf-8"))["labels"][0]["live_test"]["events"] == 2
