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
PENDING_DELETE_INTERVAL = timedelta(hours=2)
PENDING_DELETE_DAYS = 5         # typical gap between pending delete and the domain dropping
ERROR_RETRY = timedelta(hours=1)
NEAR_EXPIRY_DAYS = 30
EXPIRY_THRESHOLDS = (30, 7, 1)  # days before expiry that trigger an alert


# Lifecycle phases after expiry, from the registry's status flags.
GRACE = "grace"
REDEMPTION = "redemption"
PENDING_DELETE = "pending_delete"
PHASE_LABELS = {GRACE: "grace period", REDEMPTION: "redemption", PENDING_DELETE: "pending delete"}


def lifecycle_phase(flags: list[str]) -> str:
    # Some registries (e.g. Verisign) also set "pending delete" during redemption,
    # so redemption wins when both are present.
    if "redemption period" in flags or "pending restore" in flags:
        return REDEMPTION
    if "pending delete" in flags:
        return PENDING_DELETE
    if "auto renew period" in flags:
        return GRACE
    return ""


@dataclass
class Alert:
    domain: str
    kind: str  # "available" | "expiring"
    title: str
    message: str


def next_interval(d: Domain, now: datetime) -> timedelta:
    if d.error:
        return ERROR_RETRY
    if d.phase == PENDING_DELETE:
        return PENDING_DELETE_INTERVAL
    if d.phase:
        return NEAR_EXPIRY_INTERVAL
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
            d.phase, d.drop_date, d.alerted_phase = "", None, ""
        else:
            d.alerted_available = False
            if old_expires and d.expires and d.expires > old_expires:
                d.alerted_threshold = None  # renewed: start the countdown alerts over
            alerts.extend(_phase_alerts(d, result, now))
            if not d.phase:
                alerts.extend(_expiry_alerts(d, now))

    # Small jitter keeps checks spread out instead of bunching up after a bulk import.
    jitter = timedelta(minutes=random.uniform(0, 20)) if not d.error else timedelta()
    d.next_check = now + next_interval(d, now) + jitter
    return alerts


def _phase_alerts(d: Domain, result: LookupResult, now: datetime) -> list[Alert]:
    old_phase = d.phase
    d.phase = lifecycle_phase(result.flags)
    if d.phase == PENDING_DELETE:
        if result.deletion:
            d.drop_date = result.deletion
        elif old_phase != PENDING_DELETE or not d.drop_date:
            d.drop_date = now + timedelta(days=PENDING_DELETE_DAYS)
    else:
        d.drop_date = result.deletion if d.phase else None
    if not d.phase:
        d.alerted_phase = ""
        return []
    if d.alerted_phase == d.phase:
        return []
    d.alerted_phase = d.phase
    if d.phase == PENDING_DELETE:
        return [Alert(d.name, "pending_delete", f"{d.name} is pending delete",
                      f"Expected to drop around {d.drop_date:%b %d, %Y}. Be ready to register it.")]
    if d.phase == REDEMPTION:
        return [Alert(d.name, "redemption", f"{d.name} is in redemption",
                      "Expired and held by the registry. The owner can still restore it for a fee.")]
    return [Alert(d.name, "grace", f"{d.name} is in its grace period",
                  "Expired, but the owner can still renew it normally.")]


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
