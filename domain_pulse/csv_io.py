"""CSV import and export."""

from __future__ import annotations

import csv
from pathlib import Path

from .rdap import is_valid, normalize
from .store import Domain, utcnow

EXPORT_FIELDS = ["domain", "status", "registrar", "expires", "days_left", "last_checked", "error"]
DOMAIN_HEADERS = {"domain", "domains", "domain name", "name", "url", "website"}


def read_domains(path: Path | str) -> tuple[list[str], list[str]]:
    """Return (valid domains, rejected values) from a CSV.

    Uses a column headed "domain" (or similar) when there is one, otherwise
    the first column. A plain one-domain-per-line text file works too.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    if not rows:
        return [], []

    col = 0
    header = [c.strip().lower() for c in rows[0]]
    for i, h in enumerate(header):
        if h in DOMAIN_HEADERS:
            col = i
            rows = rows[1:]
            break

    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if col >= len(row):
            continue
        raw = row[col].strip()
        if not raw:
            continue
        if is_valid(raw):
            name = normalize(raw)
            if name not in seen:
                seen.add(name)
                valid.append(name)
        elif raw.lower() not in DOMAIN_HEADERS:
            rejected.append(raw)
    return valid, rejected


def write_domains(path: Path | str, domains: list[Domain]) -> None:
    now = utcnow()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EXPORT_FIELDS)
        for d in domains:
            days = d.days_left(now)
            w.writerow([
                d.name, d.status, d.registrar,
                d.expires.date().isoformat() if d.expires else "",
                "" if days is None else days,
                d.last_checked.strftime("%Y-%m-%d %H:%M UTC") if d.last_checked else "",
                d.error,
            ])
