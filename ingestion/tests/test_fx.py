from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests
import responses

from dirham_watch import http
from dirham_watch.fx import (
    BamClient,
    FrankfurterClient,
    business_days,
    parse_bam,
    parse_frankfurter,
)


def test_parse_bam_real_response_keeps_duplicates_for_staging(bam_payload):
    records = parse_bam(bam_payload)

    assert len(records) == 58
    assert len({r.currency for r in records}) == 30
    assert {r.rate_date for r in records} == {date(2026, 3, 26)}
    eur = [r for r in records if r.currency == "EUR"]
    assert len(eur) == 2
    assert eur[0].mid_rate == Decimal("10.7729")
    assert eur[0].unit == 1


def test_parse_bam_keeps_the_quoting_unit(bam_payload):
    jpy = next(r for r in parse_bam(bam_payload) if r.currency == "JPY")
    assert (jpy.unit, jpy.mid_rate) == (100, Decimal("5.8475"))


def test_parse_bam_legacy_record_has_bid_ask_but_no_mid():
    # Shape of pre-2016 records, which carry achat/vente instead of moyen.
    records = parse_bam(
        [{"date": "2012-05-02T12:30:00", "libDevise": "USD", "achat": 8.5, "vente": 8.6,
          "uniteDevise": 1}]
    )  # fmt: skip
    assert records[0].mid_rate is None
    assert (records[0].bid_rate, records[0].ask_rate) == (Decimal("8.5"), Decimal("8.6"))


@pytest.mark.parametrize(
    "row",
    [
        {"date": "2026-03-26T12:30:00", "libDevise": "EU", "moyen": 1, "uniteDevise": 1},
        {"date": "2026-03-26T12:30:00", "libDevise": "EUR", "moyen": 1, "uniteDevise": 0},
        {"date": "2026-03-26T12:30:00", "libDevise": "EUR", "achat": 1, "uniteDevise": 1},
    ],
    ids=["bad-code", "zero-unit", "no-usable-price"],
)
def test_parse_bam_skips_unusable_rows(row):
    assert parse_bam([row]) == []


def test_parse_bam_rejects_non_array():
    with pytest.raises(ValueError, match="JSON array"):
        parse_bam({"statusCode": 401})


def test_parse_frankfurter_drops_the_carried_over_previous_quote():
    payload = [
        {"date": "2009-12-31", "base": "USD", "quote": "MAD", "rate": 7.8602},
        {"date": "2010-01-04", "base": "USD", "quote": "MAD", "rate": 7.8454},
        {"date": "2010-01-05", "base": "USD", "quote": "EUR", "rate": 0.69},
    ]
    records = parse_frankfurter(payload, date(2010, 1, 1), date(2010, 1, 8))
    assert [(r.rate_date, r.currency, r.unit, r.mid_rate) for r in records] == [
        (date(2010, 1, 4), "USD", 1, Decimal("7.8454"))
    ]
    assert records[0].source == "frankfurter"


def test_business_days_skip_weekends():
    days = list(business_days(date(2026, 9, 18), date(2026, 9, 22)))
    assert days == [date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)]


@responses.activate
def test_bam_client_sends_key_and_date(bam_payload):
    responses.get(BamClient.URL, json=bam_payload)

    records = BamClient("secret", requests_per_minute=0).fetch_day(date(2026, 3, 26))

    request = responses.calls[0].request
    assert request.headers["Ocp-Apim-Subscription-Key"] == "secret"
    assert "date=2026-03-26T12%3A30%3A00" in request.url
    assert len(records) == 58


def test_bam_client_paces_calls_under_the_rate_limit(monkeypatch):
    """5 calls per minute: 12 s between calls, none before the first or after the last."""
    client = BamClient("secret", requests_per_minute=5)
    sleeps, fetched = [], []
    monkeypatch.setattr("dirham_watch.fx.time.sleep", sleeps.append)
    monkeypatch.setattr(client, "fetch_day", lambda day: fetched.append(day) or [])

    days = [day for day, _ in client.fetch_range(date(2026, 9, 21), date(2026, 9, 25))]

    assert days == fetched and len(days) == 5
    assert sleeps == [12.0] * 4


@responses.activate
def test_bam_client_treats_204_as_no_quotation():
    responses.get(BamClient.URL, status=204)
    assert BamClient("secret", requests_per_minute=0).fetch_day(date(2026, 12, 25)) == []


@responses.activate
def test_frankfurter_client_requests_bam_provider_per_currency():
    responses.get(
        FrankfurterClient.URL,
        json=[{"date": "2026-09-24", "base": "EUR", "quote": "MAD", "rate": 10.9347}],
    )
    got = dict(FrankfurterClient().fetch_range(date(2026, 9, 24), date(2026, 9, 24), ["EUR"]))

    url = responses.calls[0].request.url
    assert "base=EUR" in url and "quotes=MAD" in url and "providers=BAM" in url
    assert got["EUR"][0].mid_rate == Decimal("10.9347")


@responses.activate
def test_http_get_retries_server_errors_then_succeeds():
    responses.get("https://example.test/x", status=503)
    responses.get("https://example.test/x", status=429)
    responses.get("https://example.test/x", json={"ok": True})

    response = http.get(http.build_session(), "https://example.test/x")

    assert response.json() == {"ok": True}
    assert len(responses.calls) == 3


@responses.activate
def test_http_get_does_not_retry_client_errors():
    responses.get("https://example.test/x", status=401)

    with pytest.raises(requests.HTTPError) as excinfo:
        http.get(http.build_session(), "https://example.test/x")

    assert not isinstance(excinfo.value, http.RetryableHTTPError)
    assert len(responses.calls) == 1


@responses.activate
def test_http_get_gives_up_after_six_attempts():
    responses.get("https://example.test/x", status=502)

    with pytest.raises(http.RetryableHTTPError):
        http.get(http.build_session(), "https://example.test/x")

    assert len(responses.calls) == 6


def _retry_state(response: requests.Response):
    error = http.RetryableHTTPError("429", response=response)
    return SimpleNamespace(outcome=SimpleNamespace(exception=lambda: error))


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", 7.0), ("600", 120.0), ("soon", 3.0), ("0", 3.0), ("1", 3.0)],
    ids=["honoured", "capped", "unparseable", "zero-keeps-backoff", "short-keeps-backoff"],
)
def test_wait_honours_retry_after_header(header, expected):
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = header
    wait = http.wait_retry_after(fallback=lambda state: 3.0)

    assert wait(_retry_state(response)) == expected
