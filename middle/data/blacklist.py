"""
middle/data/blacklist.py
블랙리스트 관리 · 영속화 (JSON 파일 기반)
거래 금지·상장폐지·이슈 심볼을 관리 — 랭킹 제외·Assign 차단·하단 엔진 신규 진입 차단 공용
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_BLACKLIST_PATH = Path(__file__).parent / "_blacklist.json"
# 손상 원본 백업 폴더 — 프로젝트 data/ (앱 런타임 데이터 폴더, .gitignore 'data/*' 로 git 제외) (2026-11-18 D-1·D-2·D-4)
_BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "Blacklist_Backup"
_SAVE_FAIL = "블랙리스트 저장 실패 — 변경 사항이 파일에 반영되지 않음 (재시작 시 사라짐)"


@dataclass
class BlacklistEntry:
    symbol:     str
    added_utc:  str    # "2025-03-12 14:23 UTC"
    status:     str    # Settling 표시 이름(settling._label): "SETTLING" | "HALT" | "EOD" | "DELISTING" | "DELISTED"
                       # — 매핑 밖 거래소 상태 코드는 원문 그대로 · "MANUAL"은 add() 기본값(화면 경로에서는 미사용)
    reason:     str = ""


class BlacklistManager:
    """블랙리스트 관리자 — JSON 파일 기반 영속화."""

    def __init__(self, path: Path = _BLACKLIST_PATH) -> None:
        self._path    = path
        # 기본 파일 → 프로젝트 data/Blacklist_Backup, 다른 경로(테스트 임시 파일 등) → 그 파일 옆 Blacklist_Backup
        # (테스트가 실제 백업 폴더에 파일을 남겨 앱 경고가 켜지지 않도록)
        self._backup_dir = _BACKUP_DIR if path == _BLACKLIST_PATH else path.parent / _BACKUP_DIR.name
        self._entries: dict[str, BlacklistEntry] = {}
        self._load_problem = ""   # 최근 load()가 남긴 사유 — 저장 성공 시 load_error 를 이 값으로 되돌림
        self.load_error = ""   # 로드 실패·일부 손실·손상 백업 남음·저장 실패 사유 — 비어 있지 않으면 차단 목록이 불완전
        self.load()

    # ── CRUD ──────────────────────────────────────────────────
    def add(self, symbol: str, status: str = "MANUAL", reason: str = "") -> None:
        now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        self._entries[symbol] = BlacklistEntry(
            symbol=symbol, added_utc=now_utc, status=status, reason=reason
        )
        self.save()

    def remove(self, symbol: str) -> bool:
        if symbol in self._entries:
            del self._entries[symbol]
            self.save()
            return True
        return False

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self._entries

    def get_all(self) -> list[BlacklistEntry]:
        return sorted(self._entries.values(), key=lambda e: e.added_utc, reverse=True)

    # ── 영속화 ────────────────────────────────────────────────
    def load(self) -> None:
        """파일 읽기 — 손상(파싱 실패·형식 오류·일부 항목 손상)을 발견하면 그때만 원본을 백업 폴더에 복사.
        백업 폴더에 손상 백업이 남아 있는 동안은 경고 유지 — 사용자가 확인 후 백업 파일을 지우면 해제 (D-4 ②)."""
        self._entries = {}
        problem = self._read()
        if not problem:
            left = self._backups_left()
            if left:
                problem = f"블랙리스트 손상 백업 {left}개 확인 필요 ({self._backup_dir.name} 폴더)"
                logging.warning("BlacklistManager.load — %s", problem)
        self._load_problem = problem
        self.load_error = problem

    def _read(self) -> str:
        """파일을 읽어 _entries 를 채우고 문제 사유를 반환 (정상이면 "")."""
        if not self._path.exists():
            problem = f"블랙리스트 파일 없음 ({self._path.name})"
            logging.warning("BlacklistManager.load — %s", problem)
            return problem
        try:
            # utf-8-sig — 메모장·PowerShell 편집으로 붙는 BOM 허용 (D-3: BOM 정상 파일을 파싱 실패로 처리하던 문제)
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            # 파일 전체 파싱 실패 — 원본을 백업 폴더에 보존한다 (다음 add() 의 save() 가 덮어쓰기 전).
            logging.warning("BlacklistManager.load 파싱 실패: %s", e)
            return "블랙리스트 파일 파싱 실패" + self._backup("parse")
        if not isinstance(data, list):
            # 형식 오류도 원본 보존 (D-1: 보존 없이 다음 저장에서 덮어써 영구 소실되던 문제)
            logging.warning("BlacklistManager.load — 최상위가 list 가 아님")
            return "블랙리스트 파일 형식 오류 (최상위가 list 아님)" + self._backup("format")
        skipped = 0
        for d in data:
            try:
                self._entries[d["symbol"]] = BlacklistEntry(**d)
            except Exception:
                skipped += 1
        if skipped:
            # 일부 항목 손상도 원본 보존 (D-2: 다음 저장에서 손상 항목이 영구 삭제되던 문제)
            logging.warning("BlacklistManager.load — 손상 항목 %d건 건너뜀, %d건 로드",
                            skipped, len(self._entries))
            return f"블랙리스트 손상 항목 {skipped}건 제외" + self._backup("partial")
        return ""

    def _backup(self, tag: str) -> str:
        """원본을 백업 폴더에 _blacklist_YYYYMMDD-HHMMSS_<tag>.json 으로 복사 (같은 이름이 있으면 _1, _2 … — 이전 백업
        덮어쓰기 방지, D-4). 원본 파일은 그대로 둔다. 성공 시 "", 실패 시 경고 문구에 붙일 " — 백업 실패" 반환."""
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            dst = self._backup_dir / f"_blacklist_{time.strftime('%Y%m%d-%H%M%S')}_{tag}.json"
            n = 1
            while dst.exists():
                dst = self._backup_dir / f"_blacklist_{time.strftime('%Y%m%d-%H%M%S')}_{tag}_{n}.json"
                n += 1
            shutil.copy2(self._path, dst)
            logging.warning("BlacklistManager.load — 손상 원본을 %s 에 보존", dst)
            return ""
        except Exception as e:
            logging.warning("BlacklistManager.load — 손상 원본 백업 실패: %s", e)
            return " — 백업 실패"

    def _backups_left(self) -> int:
        """백업 폴더에 남은 손상 백업 수 (_blacklist_*.json)."""
        try:
            return len(list(self._backup_dir.glob("_blacklist_*.json")))
        except Exception:
            return 0

    def save(self) -> None:
        # 임시 파일에 먼저 쓰고 os.replace 로 원자적 교체 —
        # write_text 는 대상 파일을 먼저 0바이트로 truncate 하므로
        # 쓰기 도중 종료되면 기존 목록이 전부 소실된다.
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(
                json.dumps([asdict(e) for e in self._entries.values()],
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
            if self._load_problem.startswith("블랙리스트 파일 없음"):
                self._load_problem = ""            # 파일이 생김 — 재시작 전까지 '파일 없음' 경고가 남던 문제 (2026-11-22)
            self.load_error = self._load_problem   # 저장 성공 — 직전 저장 실패 경고 해제
        except Exception as e:
            # D-5: 메모리(화면·엔진)는 바뀌었지만 파일은 그대로 — 엔진 경고(blacklist_problem)로 알리고 임시 파일 정리
            logging.warning("BlacklistManager.save 실패 (%d건 미저장): %s",
                            len(self._entries), e)
            self.load_error = _SAVE_FAIL
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

