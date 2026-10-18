"""
middle/col1_ranking_blacklist/blacklist.py
블랙리스트 관리 · 영속화 (JSON 파일 기반)
거래 금지·상장폐지·이슈 심볼을 관리하고 랭킹에서 제외
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_BLACKLIST_PATH = Path(__file__).parent / "_blacklist.json"


@dataclass
class BlacklistEntry:
    symbol:     str
    added_utc:  str    # "2025-03-12 14:23 UTC"
    status:     str    # "DELISTED" | "SETTLING" | "HALT" | "MANUAL"
    reason:     str = ""


class BlacklistManager:
    """블랙리스트 관리자 — JSON 파일 기반 영속화."""

    def __init__(self, path: Path = _BLACKLIST_PATH) -> None:
        self._path    = path
        self._entries: dict[str, BlacklistEntry] = {}
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
        self._entries = {}
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            # 파일 전체 파싱 실패 — 원본을 보존한다.
            # 보존하지 않으면 다음 add() 의 save() 가 빈 목록으로 덮어써
            # 기존 등록분이 영구 소실된다.
            bad = self._path.with_name(self._path.name + ".corrupt")
            try:
                os.replace(self._path, bad)
                logging.warning("BlacklistManager.load 파싱 실패 — 원본을 %s 로 보존: %s",
                                bad.name, e)
            except Exception:
                logging.warning("BlacklistManager.load 파싱 실패: %s", e)
            return
        if not isinstance(data, list):
            logging.warning("BlacklistManager.load — 최상위가 list 가 아님")
            return
        skipped = 0
        for d in data:
            try:
                self._entries[d["symbol"]] = BlacklistEntry(**d)
            except Exception:
                skipped += 1
        if skipped:
            logging.warning("BlacklistManager.load — 손상 항목 %d건 건너뜀, %d건 로드",
                            skipped, len(self._entries))

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
        except Exception as e:
            logging.warning("BlacklistManager.save 실패 (%d건 미저장): %s",
                            len(self._entries), e)

