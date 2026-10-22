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
