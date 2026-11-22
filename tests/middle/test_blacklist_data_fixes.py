"""
tests/middle/test_blacklist_data_fixes.py
블랙리스트 파일 손상·저장 실패 처리 (2026-11-18 D-1~D-5) — 모두 tmp_path 임시 경로 (실제 _blacklist.json·data/Blacklist_Backup 미사용)
 D-1 최상위 형식 오류 → 원본 백업 (기존: 보존 없이 다음 저장에서 소실)
 D-2 일부 항목 손상 → 원본 백업 (기존: 다음 저장에서 손상 항목 영구 삭제)
 D-3 BOM 붙은 정상 파일 → 정상 로드 (기존: 파싱 실패로 차단 전체 해제)
 D-4 파싱 실패 → 원본은 그대로 두고 백업 · 재손상 시 이전 백업 보존 · 백업이 남아 있는 동안 경고 유지
 D-5 저장 실패 → 엔진 경고(load_error)·임시 파일 정리, 다음 저장 성공 시 해제
"""
import json
from pathlib import Path

import middle.data.blacklist as bl_mod
from middle.data.blacklist import BlacklistManager

_E = {"symbol": "AUSDT", "added_utc": "2026-11-18 00:00 UTC", "status": "SETTLING", "reason": ""}


def _file(tmp_path, text=None, raw=None):
    p = tmp_path / "_blacklist.json"
    if raw is not None:
        p.write_bytes(raw)
    elif text is not None:
        p.write_text(text, encoding="utf-8")
    return p


def _backups(tmp_path):
    d = tmp_path / "Blacklist_Backup"
    return sorted(f.name for f in d.glob("*")) if d.exists() else []


def test_backup_folder_location(tmp_path):
    assert bl_mod._BACKUP_DIR == Path(bl_mod.__file__).resolve().parents[2] / "data" / "Blacklist_Backup"
    assert BlacklistManager(_file(tmp_path, "[]"))._backup_dir == tmp_path / "Blacklist_Backup"   # 기본 파일 외 경로 = 파일 옆


def test_normal_file_makes_no_backup(tmp_path):
    m = BlacklistManager(_file(tmp_path, json.dumps([_E])))
    m.add("BUSDT", status="HALT")
    assert BlacklistManager(m._path).load_error == "" and not (tmp_path / "Blacklist_Backup").exists()


def test_d3_bom_file_loads(tmp_path):
    m = BlacklistManager(_file(tmp_path, raw=b"\xef\xbb\xbf" + json.dumps([_E]).encode("utf-8")))
    assert m.load_error == "" and m.is_blacklisted("AUSDT") and _backups(tmp_path) == []


def test_d1_format_error_backed_up_and_warning_kept(tmp_path):
    original = json.dumps({"entries": [_E]})
    p = _file(tmp_path, original)
    m = BlacklistManager(p)
    assert m.load_error.startswith("블랙리스트 파일 형식 오류")
    (name,) = _backups(tmp_path)
    assert name.startswith("_blacklist_") and name.endswith("_format.json")
    assert (tmp_path / "Blacklist_Backup" / name).read_text(encoding="utf-8") == original   # 원본 그대로 보존
    m.add("BUSDT", status="HALT")                                                          # 파일 덮어쓰기
    m2 = BlacklistManager(p)
    assert [e.symbol for e in m2.get_all()] == ["BUSDT"]
    assert m2.load_error == "블랙리스트 손상 백업 1개 확인 필요 (Blacklist_Backup 폴더)"   # 재시작 후에도 경고 유지


def test_d2_partial_damage_backed_up(tmp_path):
    original = json.dumps([_E, {"symbol": "CUSDT", "status": "X"}])
    p = _file(tmp_path, original)
    m = BlacklistManager(p)
    assert m.load_error == "블랙리스트 손상 항목 1건 제외" and m.is_blacklisted("AUSDT")
    (name,) = _backups(tmp_path)
    assert name.endswith("_partial.json")
    assert "CUSDT" in (tmp_path / "Blacklist_Backup" / name).read_text(encoding="utf-8")   # 손상 항목 보존
    m.add("BUSDT", status="HALT")
    assert BlacklistManager(p).load_error.startswith("블랙리스트 손상 백업 1개")


def test_d4_parse_failure_keeps_original_no_overwrite_and_clears_after_user_delete(tmp_path):
    p = _file(tmp_path, "[{broken")
    m = BlacklistManager(p)
    assert m.load_error == "블랙리스트 파일 파싱 실패" and p.exists()                       # 원본을 옮기지 않음
    assert len(_backups(tmp_path)) == 1 and _backups(tmp_path)[0].endswith("_parse.json")
    p.write_text("[{broken again", encoding="utf-8")
    BlacklistManager(p)                                                                     # 재손상
    assert len(_backups(tmp_path)) == 2                                                     # 이전 백업 덮어쓰지 않음
    p.write_text(json.dumps([_E]), encoding="utf-8")                                         # 사용자가 복구
    assert BlacklistManager(p).load_error.startswith("블랙리스트 손상 백업 2개")              # 백업 남아 있는 동안 경고
    for f in (tmp_path / "Blacklist_Backup").glob("*"):
        f.unlink()                                                                          # 사용자가 확인 후 삭제
    assert BlacklistManager(p).load_error == ""


def test_d5_save_failure_warns_and_cleans_tmp(tmp_path, monkeypatch):
    p = _file(tmp_path, json.dumps([_E]))
    m = BlacklistManager(p)

    def _fail(src, dst):
        raise OSError("대상 잠김")
    monkeypatch.setattr(bl_mod.os, "replace", _fail)
    m.add("BUSDT", status="HALT")
    assert m.is_blacklisted("BUSDT")                                                        # 화면·엔진은 등록 상태
    assert m.load_error == bl_mod._SAVE_FAIL                                                # 엔진 경고(blacklist_problem)
    assert not p.with_name(p.name + ".tmp").exists()                                        # 임시 파일 정리
    assert "BUSDT" not in p.read_text(encoding="utf-8")                                     # 파일은 그대로
    monkeypatch.undo()
    m.remove("BUSDT")                                                                       # 다음 저장 성공
    assert m.load_error == ""


def test_missing_file_warning_cleared_after_first_save(tmp_path):
    """경미 ④ 파일이 없던 상태에서 첫 저장 성공 → '파일 없음' 경고 해제 (기존: 재시작 전까지 유지)."""
    m = BlacklistManager(tmp_path / "_blacklist.json")
    assert m.load_error.startswith("블랙리스트 파일 없음")
    m.add("AUSDT", status="HALT")
    assert m.load_error == "" and (tmp_path / "_blacklist.json").exists()
