from datetime import datetime, timedelta, timezone

import pytest

from domain_pulse import csv_io, monitor
from domain_pulse.rdap import AVAILABLE, REGISTERED, LookupResult, RdapClient, is_valid, normalize, parse_domain
from domain_pulse.store import Domain, Store

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

RDAP_SAMPLE = {
    "objectClassName": "domain",
    "ldhName": "EXAMPLE.COM",
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-08-13T04:00:00Z"},
    ],
    "entities": [
        {"roles": ["registrar"], "handle": "376",
         "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "RESERVED-IANA"]]]},
    ],
}


class FakeResp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self.routes[url]


BOOTSTRAP = {"services": [[["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
                          [["co.uk", "uk"], ["http://x/", "https://rdap.nominet.uk/uk/"]]]}


def client(tmp_path, routes):
    routes = {"https://data.iana.org/rdap/dns.json": FakeResp(200, BOOTSTRAP), **routes}
    return RdapClient(tmp_path, session=FakeSession(routes))


def test_parse_domain():
    r = parse_domain("example.com", RDAP_SAMPLE)
    assert r.status == REGISTERED
    assert r.registrar == "RESERVED-IANA"
    assert r.expires == datetime(2027, 8, 13, 4, tzinfo=timezone.utc)


def test_lookup_registered_and_available(tmp_path):
    c = client(tmp_path, {
        "https://rdap.verisign.com/com/v1/domain/example.com": FakeResp(200, RDAP_SAMPLE),
        "https://rdap.verisign.com/com/v1/domain/free-name-xyz.com": FakeResp(404),
    })
    assert c.lookup("https://www.Example.com/").status == REGISTERED
    assert c.lookup("free-name-xyz.com").status == AVAILABLE
    assert (tmp_path / "rdap_bootstrap.json").exists()


def test_lookup_picks_https_and_unknown_tld(tmp_path):
    c = client(tmp_path, {})
    assert c.server_for("shop.co.uk") == "https://rdap.nominet.uk/uk/"
    r = c.lookup("foo.zzz")
    assert r.error and r.status == "unknown"


def test_normalize_and_validate():
    assert normalize(" HTTPS://www.BizHostNC.com/path ") == "bizhostnc.com"
    assert is_valid("bizhostnc.com")
    assert not is_valid("not a domain")
    assert not is_valid("localhost")


def test_csv_roundtrip(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("Notes,Domain\nmine,bizhostnc.com\ndup,BizHostNC.com\nbad,hello world\n,\nx,example.org\n")
    valid, rejected = csv_io.read_domains(src)
    assert valid == ["bizhostnc.com", "example.org"]
    assert rejected == ["hello world"]

    plain = tmp_path / "plain.csv"
    plain.write_text("a.com\nb.net\n")
    assert csv_io.read_domains(plain)[0] == ["a.com", "b.net"]

    out = tmp_path / "out.csv"
    csv_io.write_domains(out, [Domain("a.com", status=AVAILABLE),
                               Domain("b.net", status=REGISTERED, expires=NOW + timedelta(days=10))])
    lines = out.read_text().splitlines()
    assert lines[0].startswith("domain,status")
    assert lines[1].startswith("a.com,available")


def test_store(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    assert s.add(["a.com", "b.com", "a.com"]) == 2
    d = s.next_due()
    d.status = REGISTERED
    d.next_check = datetime.now(timezone.utc) + timedelta(days=1)
    s.save(d)
    assert s.due_count() == 1
    s.mark_all_due()
    assert s.due_count() == 2
    s.remove(["a.com"])
    assert [x.name for x in s.all()] == ["b.com"]


def test_available_alert_once():
    d = Domain("x.com", status=REGISTERED)
    alerts = monitor.apply_result(d, LookupResult("x.com", AVAILABLE), NOW)
    assert [a.kind for a in alerts] == ["available"]
    assert monitor.apply_result(d, LookupResult("x.com", AVAILABLE), NOW) == []
    assert d.next_check - NOW >= monitor.DEFAULT_INTERVAL


def test_expiry_thresholds_and_renewal():
    d = Domain("x.com")
    reg = lambda days: LookupResult("x.com", REGISTERED, expires=NOW + timedelta(days=days, hours=1))
    assert monitor.apply_result(d, reg(90), NOW) == []
    assert d.next_check - NOW >= monitor.DEFAULT_INTERVAL

    assert len(monitor.apply_result(d, reg(25), NOW)) == 1        # crosses 30
    assert d.next_check - NOW < monitor.DEFAULT_INTERVAL           # watched closer
    assert monitor.apply_result(d, reg(25), NOW) == []             # no repeat
    assert len(monitor.apply_result(d, reg(6), NOW)) == 1          # crosses 7
    assert len(monitor.apply_result(d, reg(0), NOW)) == 1          # crosses 1
    assert monitor.apply_result(d, reg(400), NOW) == []            # renewed
    assert d.alerted_threshold is None
    assert len(monitor.apply_result(d, reg(20), NOW)) == 1


def test_error_keeps_status_and_retries_soon():
    d = Domain("x.com", status=REGISTERED)
    monitor.apply_result(d, LookupResult("x.com", "unknown", error="timeout"), NOW)
    assert d.status == REGISTERED and d.error == "timeout"
    assert d.next_check - NOW == monitor.ERROR_RETRY


def test_parse_status_flags_and_deletion_event():
    data = {**RDAP_SAMPLE, "status": ["Pending Delete", "client hold"],
            "events": RDAP_SAMPLE["events"] + [{"eventAction": "deletion", "eventDate": "2026-10-30T18:00:00Z"}]}
    r = parse_domain("example.com", data)
    assert r.flags == ["pending delete", "client hold"]
    assert r.deletion == datetime(2026, 10, 30, 18, tzinfo=timezone.utc)


def test_lifecycle_phase():
    assert monitor.lifecycle_phase(["active"]) == ""
    assert monitor.lifecycle_phase(["auto renew period"]) == monitor.GRACE
    assert monitor.lifecycle_phase(["pending delete", "redemption period"]) == monitor.REDEMPTION
    assert monitor.lifecycle_phase(["pending delete"]) == monitor.PENDING_DELETE


def test_deletion_lifecycle_alerts_and_drop():
    d = Domain("x.com")
    expired = NOW - timedelta(days=40)
    reg = lambda flags, deletion=None: LookupResult("x.com", REGISTERED, expires=expired, flags=flags, deletion=deletion)

    alerts = monitor.apply_result(d, reg(["redemption period", "pending delete"]), NOW)
    assert [a.kind for a in alerts] == ["redemption"]           # no "expired N days" alert on top
    assert monitor.apply_result(d, reg(["redemption period"]), NOW) == []

    alerts = monitor.apply_result(d, reg(["pending delete"]), NOW)
    assert [a.kind for a in alerts] == ["pending_delete"]
    assert d.drop_date == NOW + timedelta(days=monitor.PENDING_DELETE_DAYS)
    assert d.next_check - NOW < timedelta(hours=3)               # watched closely

    later = NOW + timedelta(hours=2)
    assert monitor.apply_result(d, reg(["pending delete"]), later) == []
    assert d.drop_date == NOW + timedelta(days=monitor.PENDING_DELETE_DAYS)  # estimate kept

    published = NOW + timedelta(days=3)
    monitor.apply_result(d, reg(["pending delete"], deletion=published), later)
    assert d.drop_date == published                               # registry date wins

    alerts = monitor.apply_result(d, LookupResult("x.com", AVAILABLE), later)
    assert [a.kind for a in alerts] == ["available"]
    assert d.phase == "" and d.drop_date is None


def test_store_migrates_old_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE domains (name TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
        registrar TEXT NOT NULL DEFAULT '', expires TEXT, last_checked TEXT, next_check TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '', alerted_available INTEGER NOT NULL DEFAULT 0,
        alerted_threshold INTEGER, added TEXT NOT NULL)""")
    conn.execute("INSERT INTO domains (name, next_check, added) VALUES ('a.com', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.close()
    s = Store(path)
    d = s.get("a.com")
    assert d.phase == ""
    d.phase, d.drop_date = monitor.PENDING_DELETE, NOW
    s.save(d)
    assert Store(path).get("a.com").drop_date == NOW


def test_csv_export_lifecycle(tmp_path):
    out = tmp_path / "out.csv"
    csv_io.write_domains(out, [Domain("x.com", status=REGISTERED, phase=monitor.PENDING_DELETE, drop_date=NOW)])
    header, row = out.read_text().splitlines()
    assert header.split(",")[2] == "lifecycle"
    assert "pending delete" in row and "2026-10-22" in row
