"""Check scheduling and alert rules, independent of the UI.

Pacing: one lookup per tick. Each domain is rechecked once a day, so 250
domains average one quiet request every ~6 minutes. Domains near expiry are
watched more closely, and failures back off for an hour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from .rdap import AVAILABLE, REGISTERED, LookupResult
from .store import Domain, utcnow

TICK_SECONDS = 4              # minimum gap between any two lookups
DEFAULT_INTERVAL = timedelta(hours=24)
NEAR_EXPIRY_INTERVAL = timedelta(hours=6)
ERROR_RETRY = timedelta(hours=1)
NEAR_EXPIRY_DAYS = 30
EXPIRY_THRESHOLDS = (30, 7, 1)  # days before expiry that trigger an alert


@dataclass
class Alert:
    domain: str
    kind: str  # "available" | "expiring"
    title: str
    message: str


def next_interval(d: Domain, now: datetime) -> timedelta:
    if d.error:
        return ERROR_RETRY
    days = d.days_left(now)
    if d.status == REGISTERED and days is not None and days <= NEAR_EXPIRY_DAYS:
        return NEAR_EXPIRY_INTERVAL
    return DEFAULT_INTERVAL


def apply_result(d: Domain, result: LookupResult, now: datetime | None = None) -> list[Alert]:
    """Update a domain with a lookup result and return any alerts to show."""
    now = now or utcnow()
    alerts: list[Alert] = []
    d.last_checked = now

    if result.error:
        # Keep the last good status; just record the problem and retry sooner.
        d.error = result.error
    else:
        d.error = ""
        old_expires = d.expires
        d.status = result.status
        d.registrar = result.registrar
        d.expires = result.expires

        if d.status == AVAILABLE:
            if not d.alerted_available:
                alerts.append(Alert(d.name, "available", f"{d.name} is available",
                                    "Register it now before someone else does."))
                d.alerted_available = True
            d.alerted_threshold = None
        else:
            d.alerted_available = False
            if old_expires and d.expires and d.expires > old_expires:
                d.alerted_threshold = None  # renewed: start the countdown alerts over
            alerts.extend(_expiry_alerts(d, now))

    # Small jitter keeps checks spread out instead of bunching up after a bulk import.
    jitter = timedelta(minutes=random.uniform(0, 20)) if not d.error else timedelta()
    d.next_check = now + next_interval(d, now) + jitter
    return alerts


def _expiry_alerts(d: Domain, now: datetime) -> list[Alert]:
    days = d.days_left(now)
    if days is None:
        return []
    crossed = [t for t in EXPIRY_THRESHOLDS if days <= t]
    if not crossed:
        return []
    threshold = min(crossed)
    if d.alerted_threshold is not None and d.alerted_threshold <= threshold:
        return []
    d.alerted_threshold = threshold
    if days < 0:
        msg = f"Expired {-days} day{'s' if days != -1 else ''} ago."
    elif days == 0:
        msg = "Expires today."
    else:
        msg = f"Expires in {days} day{'s' if days != 1 else ''} ({d.expires:%b %d, %Y})."
    return [Alert(d.name, "expiring", f"{d.name} is expiring", msg)]
