"""RDAP lookups: registered/available status, registrar and expiry date.

RDAP is the structured successor to WHOIS. IANA publishes which RDAP server
answers for each TLD; we cache that bootstrap file for a week.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_MAX_AGE = 7 * 24 * 3600
TIMEOUT = 15
HEADERS = {"Accept": "application/rdap+json", "User-Agent": "DomainPulse/0.1"}

REGISTERED = "registered"
AVAILABLE = "available"
UNKNOWN = "unknown"


@dataclass
class LookupResult:
    domain: str
    status: str
    registrar: str = ""
    expires: datetime | None = None
    error: str = ""


class RdapClient:
    def __init__(self, cache_dir: Path, session: requests.Session | None = None):
        self.cache_file = Path(cache_dir) / "rdap_bootstrap.json"
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self._services: dict[str, str] | None = None

    # -- bootstrap ---------------------------------------------------------
    def _load_bootstrap(self) -> dict[str, str]:
        if self._services is not None:
            return self._services
        data = None
        fresh = self.cache_file.exists() and time.time() - self.cache_file.stat().st_mtime < BOOTSTRAP_MAX_AGE
        if fresh:
            data = json.loads(self.cache_file.read_text())
        else:
            try:
                resp = self.session.get(BOOTSTRAP_URL, timeout=TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(data))
            except (requests.RequestException, ValueError):
                if not self.cache_file.exists():
                    raise
                data = json.loads(self.cache_file.read_text())
        services: dict[str, str] = {}
        for tlds, urls in data.get("services", []):
            https = [u for u in urls if u.startswith("https://")] or urls
            for tld in tlds:
                services[tld.lower()] = https[0].rstrip("/") + "/"
        self._services = services
        return services

    def server_for(self, domain: str) -> str | None:
        services = self._load_bootstrap()
        labels = domain.lower().split(".")
        # Longest suffix wins (e.g. "co.uk" before "uk").
        for i in range(1, len(labels)):
            suffix = ".".join(labels[i:])
            if suffix in services:
                return services[suffix]
        return None

    # -- lookup ------------------------------------------------------------
    def lookup(self, domain: str) -> LookupResult:
        domain = normalize(domain)
        try:
            server = self.server_for(domain)
        except (requests.RequestException, ValueError) as exc:
            return LookupResult(domain, UNKNOWN, error=f"RDAP bootstrap failed: {exc}")
        if not server:
            return LookupResult(domain, UNKNOWN, error="TLD has no RDAP server")
        try:
            resp = self.session.get(f"{server}domain/{domain}", timeout=TIMEOUT)
        except requests.RequestException as exc:
            return LookupResult(domain, UNKNOWN, error=str(exc))
        if resp.status_code == 404:
            return LookupResult(domain, AVAILABLE)
        if resp.status_code == 429:
            return LookupResult(domain, UNKNOWN, error="Rate limited by registry")
        if resp.status_code != 200:
            return LookupResult(domain, UNKNOWN, error=f"HTTP {resp.status_code}")
        try:
            return parse_domain(domain, resp.json())
        except ValueError as exc:
            return LookupResult(domain, UNKNOWN, error=f"Bad RDAP response: {exc}")


def parse_domain(domain: str, data: dict) -> LookupResult:
    expires = None
    for event in data.get("events", []):
        if event.get("eventAction") == "expiration" and event.get("eventDate"):
            expires = parse_date(event["eventDate"])
    return LookupResult(domain, REGISTERED, registrar=_registrar(data), expires=expires)


def _registrar(data: dict) -> str:
    for entity in data.get("entities", []):
        if "registrar" not in entity.get("roles", []):
            continue
        vcard = entity.get("vcardArray") or [None, []]
        for prop in vcard[1]:
            if prop and prop[0] == "fn":
                return str(prop[3])
        return entity.get("handle", "")
    return ""


def parse_date(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def normalize(domain: str) -> str:
    d = domain.strip().lower()
    for prefix in ("http://", "https://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.split("/")[0].strip(".")
    if d.startswith("www."):
        d = d[4:]
    return d.encode("idna").decode("ascii") if any(ord(c) > 127 for c in d) else d


def is_valid(domain: str) -> bool:
    d = normalize(domain)
    if "." not in d or len(d) > 253:
        return False
    return all(0 < len(label) <= 63 and label.replace("-", "").isalnum() for label in d.split("."))
