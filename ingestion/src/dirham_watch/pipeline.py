"""Entry points shared by the CLI and the Airflow DAGs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from dirham_watch import db
from dirham_watch.config import Settings
from dirham_watch.cpi import CpiRow, HcpClient, parse_indicator
from dirham_watch.fx import BamClient, FrankfurterClient

log = logging.getLogger(__name__)


def init_db(settings: Settings) -> None:
    with db.connect(settings) as conn:
        db.init_schema(conn)


def load_fx(
    settings: Settings, start: date, end: date, source: str | None = None
) -> dict[str, Any]:
    """Fetch rates for [start, end] and replace that window in raw.fx_rates."""
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    source = settings.resolved_fx_source(source)
    rows = 0
    latest: date | None = None

    with db.connect(settings) as conn:
        db.init_schema(conn)
        if source == "bam":
            client = BamClient(
                settings.bam_api_key or "", requests_per_minute=settings.bam_requests_per_minute
            )
            for day, records in client.fetch_range(start, end):
                # On holidays the API can echo an earlier quote; keep only the requested day.
                records = [r for r in records if r.rate_date == day]
                rows += db.replace_fx(conn, records, source="bam", start=day, end=day)
                if records:
                    latest = day
                log.info("bam %s: %d rates", day, len(records))
        else:
            client = FrankfurterClient()
            for currency, records in client.fetch_range(start, end, settings.fx_currencies):
                rows += db.replace_fx(
                    conn, records, source="frankfurter", start=start, end=end,
                    currencies=[currency],
                )  # fmt: skip
                if records:
                    newest = max(r.rate_date for r in records)
                    latest = newest if latest is None else max(latest, newest)
                log.info("frankfurter %s %s..%s: %d rates", currency, start, end, len(records))

    summary = {
        "source": source,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
        "latest_rate_date": latest.isoformat() if latest else None,
    }
    log.info("FX load done: %s", summary)
    return summary


def load_cpi(settings: Settings, force: bool = False) -> dict[str, Any]:
    """Load the CPI from HCP's API unless the same version is already in raw.

    The API has no cheap "has it changed" call, so the indicator is always downloaded; the
    database is only rewritten, and dbt only rebuilt, when HCP's update date moved.
    """
    resource, payload = HcpClient(settings.hcp_api_url).fetch_indicator(settings.cpi_indicator)

    with db.connect(settings) as conn:
        db.init_schema(conn)
        if not force and db.cpi_loaded_version(conn, resource.dataset_id) == (
            resource.resource_id,
            resource.last_modified,
        ):
            log.info("CPI %s unchanged since %s", resource.dataset_id, resource.last_modified)
            return {"status": "unchanged", "resource_id": resource.resource_id,
                    "resource_last_modified": _iso(resource.last_modified)}  # fmt: skip

        latest_month: date | None = None

        def tracked(rows: Iterator[CpiRow]) -> Iterator[CpiRow]:
            nonlocal latest_month
            for row in rows:
                if row.index_value != "-" and (
                    latest_month is None or row.period_month > latest_month
                ):
                    latest_month = row.period_month
                yield row

        # A malformed payload raises mid-stream and rolls the replacement back.
        count = db.replace_cpi(conn, resource, tracked(parse_indicator(payload)))

    summary = {
        "status": "loaded",
        "resource_id": resource.resource_id,
        "resource_last_modified": _iso(resource.last_modified),
        "rows": count,
        "latest_month": latest_month.isoformat() if latest_month else None,
    }
    log.info("CPI load done: %s", summary)
    return summary


def export_rates(settings: Settings, out_path: Path) -> dict[str, Any]:
    """Write the latest daily rates as a small JSON file for client apps (e.g. Fatoura).

    Check the Bank Al-Maghrib terms of use before publishing this file anywhere public.
    """
    with db.connect(settings) as conn:
        rows = conn.execute(
            """
            select rate_date, currency_code, mad_per_unit, source_system
            from staging.stg_fx_daily
            where rate_date = (select max(rate_date) from staging.stg_fx_daily)
            order by currency_code
            """
        ).fetchall()
    if not rows:
        raise RuntimeError("staging.stg_fx_daily is empty: run the FX load and dbt first")

    document = {
        "base": "MAD",
        "description": "MAD per 1 unit of each currency (Bank Al-Maghrib transfer rate, mid)",
        "date": rows[0][0].isoformat(),
        "source": sorted({r[3] for r in rows}),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rates": {r[1]: float(r[2]) for r in rows},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    log.info("Wrote %d rates for %s to %s", len(rows), document["date"], out_path)
    return {"path": str(out_path), "date": document["date"], "currencies": len(rows)}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
