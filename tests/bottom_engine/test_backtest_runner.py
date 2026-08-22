"""
tests/bottom/test_backtest_runner.py
_fmt_elapsed / _grade_ok 순수 함수 경계값 테스트 (13 + 6건).
mock/patch/MagicMock 사용 없음.
"""
import pytest
from bottom_engine.backtest.backtest_runner import _fmt_elapsed, _grade_ok
from bottom_engine.engine_core.quality_grader import QualityGrader


# ── _fmt_elapsed 왕복 13경계값 ───────────────────────────────────────
# 경계값: minutes → _fmt_elapsed() → _duration_score() 왕복 검증

_ELAPSED_CASES = [
    # (minutes, expected_str, expected_score)
    (-1,     None,       3),   # 음수 → None → 점수 3
    (0,      "방금",     5),   # 0분 정각
    (0.5,    "방금",     5),   # 1분 미만
    (0.999,  "방금",     5),   # 1분 직전
    (1,      "1분 전",  10),   # 1분 경계 (floor)
    (1.9,    "1분 전",  10),   # 1분 초과 미만
    (2,      "2분 전",  10),   # 2분
    (4,      "4분 전",  15),   # 3분 이상 → score 15
    (5,      "5분 전",  20),   # 5분 경계 (floor)
    (9,      "9분 전",  20),   # 10분 직전
    (10,     "10분 전", 25),   # 10분 경계 (floor)
    (59,     "59분 전", 25),   # 60분 직전
    (60,     "1시간 전", 25),  # 60분 정각
]


class TestFmtElapsed:
    @pytest.mark.parametrize("minutes,expected_str,_score", _ELAPSED_CASES)
    def test_fmt_elapsed_output(self, minutes, expected_str, _score):
        assert _fmt_elapsed(minutes) == expected_str

    @pytest.mark.parametrize("minutes,_str,expected_score", _ELAPSED_CASES)
    def test_fmt_elapsed_duration_score_roundtrip(self, minutes, _str, expected_score):
        elapsed = _fmt_elapsed(minutes)
        score = QualityGrader._duration_score({"tf5": {"elapsed": elapsed}})
        assert score == expected_score


# ── _grade_ok 6경계값 ────────────────────────────────────────────────

class TestGradeOk:
    @pytest.mark.parametrize("computed,required,expected", [
        ("A", None, True),   # required=None → 항상 통과
        ("D", None, True),   # required=None → 항상 통과
        ("A", "B",  True),   # A(0) <= B(1) — A가 더 엄격
        ("B", "B",  True),   # 동일 등급
        ("C", "B",  False),  # C(2) > B(1) — 미달
        ("B", "A",  False),  # B(1) > A(0) — 미달
    ])
    def test_grade_ok(self, computed, required, expected):
        assert _grade_ok(computed, required) is expected