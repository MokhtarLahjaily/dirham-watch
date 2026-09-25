"""HCP consumer price index (IPC, base 100 = 2017), monthly.

Source: HCP's statistics database (Banque de données statistiques, https://bds.hcp.ma), whose
public API returns an indicator as JSON: two dimensions (cities, then product groups), a
list of periods (`2026M5`) and one value per `"{city id}.{group id}_{period}"` key.

It replaced the data.gov.ma workbook, which stopped in November 2024 and whose city rows
were misaligned (see stg_cpi_monthly).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import requests

from dirham_watch import http

log = logging.getLogger(__name__)

CITY_DIMENSION = "villes"
PERIOD = re.compile(r"^(\d{4})M(\d{1,2})$")


@dataclass(frozen=True)
class CpiResource:
    dataset_id: str
    resource_id: str
    url: str
    last_modified: datetime | None


@dataclass(frozen=True)
class CpiRow:
    city: str
    product_group: str
    period_label: str
    period_month: date
    index_value: str


def parse_period(label: str) -> date:
    """`'2026M5'` -> 2026-05-01."""
    match = PERIOD.match(str(label).strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"Unrecognised CPI period: {label!r}")
    return date(int(match.group(1)), int(match.group(2)), 1)


def parse_indicator(payload: dict[str, Any]) -> Iterator[CpiRow]:
    """Melt an indicator payload to one row per city, product group and month."""
    if payload.get("isShutOff"):
        raise RuntimeError(
            f"HCP indicator {payload.get('code')} is shut off: {payload.get('shutOffComment')}"
        )
    dimensions = sorted(payload["dimensions"], key=lambda d: d["rank"])
    if len(dimensions) != 2 or dimensions[0]["label"].strip().lower() != CITY_DIMENSION:
        labels = [d["label"] for d in dimensions]
        raise ValueError(f"Expected dimensions (Villes, product groups), got {labels}")

    cities = {m["id"]: m["label"].strip() for m in dimensions[0]["modalites"]}
    groups = {m["id"]: m["label"].strip() for m in dimensions[1]["modalites"]}
    for key, cell in payload["data"].items():
        ids, _, period = key.partition("_")
        city_id, _, group_id = ids.partition(".")
        value = cell.get("value") if isinstance(cell, dict) else cell
        if value is None or str(value).strip() == "":
            continue
        yield CpiRow(
            city=cities[int(city_id)],
            product_group=groups[int(group_id)],
            period_label=period,
            period_month=parse_period(period),
            index_value=str(value).strip(),
        )


class HcpClient:
    def __init__(self, base_url: str, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or http.build_session()

    def fetch_indicator(self, code: str) -> tuple[CpiResource, dict[str, Any]]:
        """Download one indicator (the monthly CPI is about 16 MB of JSON)."""
        url = f"{self.base_url}/indicators/{code}"
        payload = http.get(self.session, url).json()
        stamp = payload.get("updatingDate")
        resource = CpiResource(
            dataset_id=code,
            resource_id=url,
            url=url,
            # Milliseconds since the epoch: when HCP last updated the indicator.
            last_modified=datetime.fromtimestamp(stamp / 1000, UTC) if stamp else None,
        )
        return resource, payload
