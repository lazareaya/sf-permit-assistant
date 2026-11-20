import httpx
import pytest

from app import config, datasf, tools

ROW = {
    "permit_number": "202604270175",
    "permit_type_definition": "otc alterations permit",
    "status": "issued",
    "status_date": "2026-05-01T10:00:00.000",
    "street_number": "781",
    "street_name": "20th",
    "street_suffix": "Av",
    "description": "kitchen remodel",
    "estimated_cost": "65000.0",
    "neighborhoods_analysis_boundaries": "Outer Richmond",
    "zipcode": "94121",
    "data_as_of": "2026-11-20T00:00:00.000",
}


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._p


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("781 20th Ave", ("781", "20th", "Av")),
        ("230 4th Avenue, San Francisco, CA 94118", ("230", "04th", "Av")),
        ("2542 Bryant Street", ("2542", "Bryant", "St")),
        ("207 Los Palmos Dr.", ("207", "Los Palmos", "Dr")),
        ("40 Sycamore", ("40", "Sycamore", None)),
    ],
)
def test_parse_address(raw, expected):
    p = datasf.parse_address(raw)
    assert (p["street_number"], p["street_name"], p["street_suffix"]) == expected


def test_parse_address_rejects_garbage():
    with pytest.raises(datasf.DataSFError) as e:
        datasf.parse_address("Market Street")
    assert e.value.code == "INVALID_ADDRESS"


def test_search_builds_soql_and_dedupes(monkeypatch):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(url=url, params=params)
        return _Resp([ROW, ROW, {**ROW, "permit_number": "202508263948"}])

    monkeypatch.setattr(httpx, "get", fake_get)
    out = tools.search_permits("781 20th Ave")
    assert seen["url"] == config.DATASF_URL
    assert "street_number='781'" in seen["params"]["$where"]
    assert "upper(street_name)=upper('20th')" in seen["params"]["$where"]
    assert seen["params"]["$order"] == "status_date DESC"
    assert out["permit_count"] == 2 and len(out["permits"]) == 2
    assert out["source"].startswith("DataSF")


def test_quotes_are_escaped_in_soql(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, params, headers, timeout: seen.update(p=params) or _Resp([ROW]),
    )
    tools.search_permits("12 O'Farrell St")
    assert "upper('O''Farrell')" in seen["p"]["$where"]


def test_cache_avoids_second_call(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: calls.append(1) or _Resp([ROW]))
    assert tools.search_permits("781 20th Ave")["from_cache"] is False
    assert tools.search_permits("781 20th Ave")["from_cache"] is True
    assert len(calls) == 1


def test_address_not_found(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp([]))
    assert tools.search_permits("99999 Market St")["error"] == "ADDRESS_NOT_FOUND"


def test_timeout(monkeypatch):
    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "get", boom)
    assert tools.search_permits("781 20th Ave")["error"] == "DATASF_TIMEOUT"


def test_unavailable_without_cache(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp({}, status=503))
    out = tools.search_permits("781 20th Ave")
    assert out["error"] == "DATASF_UNAVAILABLE" and "permits" not in out


def test_unavailable_falls_back_to_stale_cache(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp([ROW]))
    tools.search_permits("781 20th Ave")
    monkeypatch.setattr(config, "DATASF_CACHE_TTL_S", -1)  # cache now stale

    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", down)
    out = tools.search_permits("781 20th Ave")
    assert out["from_cache"] is True and "warning" in out


@pytest.mark.parametrize("bad", ["", "1", "781 20th Ave; DROP TABLE", "x" * 200])
def test_pydantic_rejects_bad_address(bad):
    assert tools.search_permits(bad)["error"] == "INVALID_INPUT"
