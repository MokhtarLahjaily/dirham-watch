"""The `raw` schema: DDL and idempotent loads.

Raw tables keep what the sources returned (including duplicate rows and '-' placeholders).
Typing, deduplication and business rules live in dbt staging models.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime

import psycopg
from psycopg import sql

from dirham_watch.config import Settings
from dirham_watch.cpi import CpiResource, CpiRow
from dirham_watch.fx import FxRecord

DDL = """
create schema if not exists {schema};

create table if not exists {schema}.fx_rates (
    source      text          not null,
    rate_date   date          not null,
    currency    text          not null,
    unit        integer       not null,
    mid_rate    numeric(18, 6),
    bid_rate    numeric(18, 6),
    ask_rate    numeric(18, 6),
    payload     jsonb         not null,
    loaded_at   timestamptz   not null default now()
);
create index if not exists fx_rates_source_date_idx on {schema}.fx_rates (source, rate_date);

comment on table {schema}.fx_rates is
    'Bank Al-Maghrib transfer rates (cours virement), MAD per unit of currency, as returned '
    'by the source. source = bam (direct API) or frankfurter (keyless mirror of BAM).';

create table if not exists {schema}.cpi_index (
    city                    text        not null,
    product_group           text        not null,
    period_label            text        not null,
    period_month            date        not null,
    index_value             text        not null,
    dataset_id              text        not null,
    resource_id             text        not null,
    resource_last_modified  timestamptz,
    loaded_at               timestamptz not null default now()
);

comment on table {schema}.cpi_index is
    'HCP consumer price index (base 100 = 2017) from the HCP statistics database API: one row '
    'per city, product group and month. index_value is text as published.';
"""


# dbt reads this schema as the `raw` source. Tests pass a throwaway schema instead.
RAW_SCHEMA = "raw"


def _lock(conn: psycopg.Connection, schema: str, name: str) -> None:
    """Serialise writers of one raw table (or the DDL) until the transaction ends.

    Two overlapping delete-then-insert loads (a daily run during a backfill) could otherwise
    both miss each other's new rows under READ COMMITTED and leave duplicates.
    """
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", [f"{schema}.{name}"])


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(**settings.conninfo(), application_name="dirham-watch")


def init_schema(conn: psycopg.Connection, schema: str = RAW_SCHEMA) -> None:
    # `create ... if not exists` is not safe against a concurrent identical statement
    # (both can pass the existence check), so DDL runs under a lock too.
    with conn.transaction():
        _lock(conn, schema, "ddl")
        conn.execute(sql.SQL(DDL).format(schema=sql.Identifier(schema)))


def replace_fx(
    conn: psycopg.Connection,
    records: Sequence[FxRecord],
    *,
    source: str,
    start: date,
    end: date,
    currencies: Iterable[str] | None = None,
    schema: str = RAW_SCHEMA,
) -> int:
    """Replace one source's rows for [start, end] (optionally for some currencies only).

    Delete-then-insert in a single transaction makes re-runs and backfills idempotent.
    """
    table = sql.Identifier(schema, "fx_rates")
    where = sql.SQL("source = %s and rate_date between %s and %s")
    params: list[object] = [source, start, end]
    if currencies is not None:
        where += sql.SQL(" and currency = any(%s)")
        params.append(list(currencies))

    with conn.transaction():
        _lock(conn, schema, "fx_rates")
        conn.execute(sql.SQL("delete from {} where {}").format(table, where), params)
        with conn.cursor().copy(
            sql.SQL(
                "copy {} (source, rate_date, currency, unit, mid_rate, bid_rate, ask_rate, "
                "payload) from stdin"
            ).format(table)
        ) as copy:
            for r in records:
                copy.write_row(
                    (
                        r.source, r.rate_date, r.currency, r.unit,
                        r.mid_rate, r.bid_rate, r.ask_rate, json.dumps(r.payload),
                    )
                )  # fmt: skip
    return len(records)


def cpi_loaded_version(
    conn: psycopg.Connection, dataset_id: str, schema: str = RAW_SCHEMA
) -> tuple[str, datetime] | None:
    row = conn.execute(
        sql.SQL(
            "select resource_id, max(resource_last_modified) from {} where dataset_id = %s "
            "group by resource_id order by 2 desc nulls last limit 1"
        ).format(sql.Identifier(schema, "cpi_index")),
        [dataset_id],
    ).fetchone()
    return (row[0], row[1]) if row else None


def replace_cpi(
    conn: psycopg.Connection,
    resource: CpiResource,
    rows: Iterable[CpiRow],
    schema: str = RAW_SCHEMA,
) -> int:
    """Each load is a full snapshot of the index, so it replaces the whole table.

    That also clears rows from an earlier source (the data.gov.ma workbook).
    """
    table = sql.Identifier(schema, "cpi_index")
    count = 0
    with conn.transaction():
        _lock(conn, schema, "cpi_index")
        conn.execute(sql.SQL("delete from {}").format(table))
        with conn.cursor().copy(
            sql.SQL(
                "copy {} (city, product_group, period_label, period_month, index_value, "
                "dataset_id, resource_id, resource_last_modified) from stdin"
            ).format(table)
        ) as copy:
            for row in rows:
                copy.write_row(
                    (
                        row.city, row.product_group, row.period_label, row.period_month,
                        row.index_value, resource.dataset_id, resource.resource_id,
                        resource.last_modified,
                    )
                )  # fmt: skip
                count += 1
    return count
