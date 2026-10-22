"""SQLite storage for watched domains and their last known state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    registrar TEXT NOT NULL DEFAULT '',
    expires TEXT,
    last_checked TEXT,
    next_check TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    alerted_available INTEGER NOT NULL DEFAULT 0,
    alerted_threshold INTEGER,
    added TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Domain:
    name: str
    status: str = "pending"
    registrar: str = ""
    expires: datetime | None = None
    last_checked: datetime | None = None
    next_check: datetime | None = None
    error: str = ""
    alerted_available: bool = False
    alerted_threshold: int | None = None

    def days_left(self, now: datetime | None = None) -> int | None:
        if not self.expires:
            return None
        return (self.expires - (now or utcnow())).days


class Store:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def add(self, names: list[str]) -> int:
        now = utcnow().isoformat()
        cur = self.conn.executemany(
            "INSERT OR IGNORE INTO domains (name, next_check, added) VALUES (?, ?, ?)",
            [(n, now, now) for n in names],
        )
        self.conn.commit()
        return cur.rowcount

    def remove(self, names: list[str]) -> None:
        self.conn.executemany("DELETE FROM domains WHERE name = ?", [(n,) for n in names])
        self.conn.commit()

    def all(self) -> list[Domain]:
        rows = self.conn.execute("SELECT * FROM domains ORDER BY name").fetchall()
        return [self._row(r) for r in rows]

    def get(self, name: str) -> Domain | None:
        row = self.conn.execute("SELECT * FROM domains WHERE name = ?", (name,)).fetchone()
        return self._row(row) if row else None

    def next_due(self, now: datetime | None = None) -> Domain | None:
        now = (now or utcnow()).isoformat()
        row = self.conn.execute(
            "SELECT * FROM domains WHERE next_check <= ? ORDER BY next_check LIMIT 1", (now,)
        ).fetchone()
        return self._row(row) if row else None

    def due_count(self, now: datetime | None = None) -> int:
        now = (now or utcnow()).isoformat()
        return self.conn.execute("SELECT COUNT(*) FROM domains WHERE next_check <= ?", (now,)).fetchone()[0]

    def mark_all_due(self, names: list[str] | None = None) -> None:
        now = utcnow().isoformat()
        if names is None:
            self.conn.execute("UPDATE domains SET next_check = ?", (now,))
        else:
            self.conn.executemany("UPDATE domains SET next_check = ? WHERE name = ?", [(now, n) for n in names])
        self.conn.commit()

    def save(self, d: Domain) -> None:
        self.conn.execute(
            """UPDATE domains SET status=?, registrar=?, expires=?, last_checked=?, next_check=?,
               error=?, alerted_available=?, alerted_threshold=? WHERE name=?""",
            (
                d.status, d.registrar,
                d.expires.isoformat() if d.expires else None,
                d.last_checked.isoformat() if d.last_checked else None,
                (d.next_check or utcnow()).isoformat(),
                d.error, int(d.alerted_available), d.alerted_threshold, d.name,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> Domain:
        return Domain(
            name=r["name"], status=r["status"], registrar=r["registrar"],
            expires=_dt(r["expires"]), last_checked=_dt(r["last_checked"]),
            next_check=_dt(r["next_check"]), error=r["error"],
            alerted_available=bool(r["alerted_available"]),
            alerted_threshold=r["alerted_threshold"],
        )
