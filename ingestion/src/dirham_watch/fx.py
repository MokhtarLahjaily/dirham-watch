"""Daily MAD exchange rates.

Two clients return the same `FxRecord` shape:

* `BamClient` calls the Bank Al-Maghrib "Cours de change" API (needs a free key from
  https://apihelpdesk.centralbankofmorocco.ma). One call per business day returns every
  quoted currency; the subscription allows 5 calls per minute.
* `FrankfurterClient` calls api.frankfurter.dev, which mirrors the same BAM transfer rates
  without a key. One call per currency returns the whole date range. Used when no BAM key
  is configured, so the pipeline runs end to end on a fresh clone.

Rates are "cours virement" (transfer rates) published around 12:30 Morocco time, expressed
as MAD per `unit` of foreign currency (JPY, SEK, NOK, DKK and XOF are quoted per 100).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import requests

from dirham_watch import http

log = logging.getLogger(__name__)

CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class FxRecord:
    source: str
    rate_date: date
    currency: str
    unit: int
    mid_rate: Decimal | None
    bid_rate: Decimal | None = None
    ask_rate: Decimal | None = None
    payload: dict[str, Any] = field(default_factory=dict, compare=False)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def business_days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def parse_bam(payload: Any) -> list[FxRecord]:
    """Parse a CoursVirement response.

    Records since 2016 carry `moyen` (mid rate); older ones only carry `achat`/`vente`
    (bid/ask), so the mid rate is left empty and derived downstream. Duplicate rows, which
    the API does return on some days, are kept as-is: deduplication belongs to staging.
    """
    if not isinstance(payload, list):
        raise ValueError(f"BAM: expected a JSON array, got {type(payload).__name__}")

    records = []
    for row in payload:
        code = str(row.get("libDevise") or "").strip().upper()
        if not CURRENCY_CODE.match(code):
            continue
        unit = int(row.get("uniteDevise") or 0)
        mid, bid, ask = (_decimal(row.get(k)) for k in ("moyen", "achat", "vente"))
        if unit <= 0 or (mid is None and (bid is None or ask is None)):
            log.warning("BAM: skipping unusable record %s", row)
            continue
        records.append(
            FxRecord(
                source="bam",
                rate_date=datetime.fromisoformat(row["date"]).date(),
                currency=code,
                unit=unit,
                mid_rate=mid,
                bid_rate=bid,
                ask_rate=ask,
                payload=row,
            )
        )
    return records


def parse_frankfurter(payload: Any, start: date, end: date) -> list[FxRecord]:
    """Parse a Frankfurter v2 `/rates?base=XXX&quotes=MAD` response.

    Frankfurter also returns the last quote before `start` so that callers always get a
    value; that row is dropped to keep loads idempotent over the requested window.
    """
    if not isinstance(payload, list):
        raise ValueError(f"Frankfurter: expected a JSON array, got {type(payload).__name__}")

    records = []
    for row in payload:
        rate_date = date.fromisoformat(row["date"])
        if not start <= rate_date <= end or row.get("quote") != "MAD":
            continue
        records.append(
            FxRecord(
                source="frankfurter",
                rate_date=rate_date,
                currency=str(row["base"]).upper(),
                unit=1,
                mid_rate=_decimal(row["rate"]),
                payload=row,
            )
        )
    return records


class BamClient:
    URL = "https://api.centralbankofmorocco.ma/cours/Version1/api/CoursVirement"

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        requests_per_minute: float = 5,
    ):
        self.api_key = api_key
        self.session = session or http.build_session()
        # Paced to stay under the subscription's rate limit instead of hitting 429s.
        self.pause_seconds = 60 / requests_per_minute if requests_per_minute else 0

    def fetch_day(self, day: date) -> list[FxRecord]:
        response = http.get(
            self.session,
            self.URL,
            params={"date": f"{day.isoformat()}T12:30:00"},
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
        )
        if response.status_code == 204 or not response.content:
            return []  # no quotation: Moroccan public holiday, 25/12 or 26/12
        return parse_bam(response.json())

    def fetch_range(self, start: date, end: date) -> Iterator[tuple[date, list[FxRecord]]]:
        """Yield `(day, records)` per business day so callers can commit day by day."""
        for i, day in enumerate(business_days(start, end)):
            if i:
                time.sleep(self.pause_seconds)
            yield day, self.fetch_day(day)


class FrankfurterClient:
    URL = "https://api.frankfurter.dev/v2/rates"

    def __init__(self, session: requests.Session | None = None, pause_seconds: float = 1.0):
        self.session = session or http.build_session()
        # A short pause between currencies: the public service rate-limits bursts.
        self.pause_seconds = pause_seconds

    def fetch_currency(self, currency: str, start: date, end: date) -> list[FxRecord]:
        response = http.get(
            self.session,
            self.URL,
            params={
                "base": currency,
                "quotes": "MAD",
                "providers": "BAM",
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
        return parse_frankfurter(response.json(), start, end)

    def fetch_range(
        self, start: date, end: date, currencies: Iterable[str]
    ) -> Iterator[tuple[str, list[FxRecord]]]:
        for i, currency in enumerate(currencies):
            if i:
                time.sleep(self.pause_seconds)
            yield currency, self.fetch_currency(currency, start, end)
