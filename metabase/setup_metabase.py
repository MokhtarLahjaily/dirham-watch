"""Provision Metabase: admin account, warehouse connection, questions and dashboard.

Idempotent: questions and the dashboard are matched by name and updated in place, so
re-running after editing a query below updates Metabase. Standard library only, so it runs
on a stock python image.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
import urllib.error
import urllib.request
from typing import Any

MB_URL = os.environ.get("MB_URL", "http://localhost:3000").rstrip("/")
PUBLIC_URL = os.environ.get("MB_PUBLIC_URL", MB_URL).rstrip("/")
ADMIN_EMAIL = os.environ["MB_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["MB_ADMIN_PASSWORD"]
DATABASE_NAME = "Dirham Watch warehouse"
DASHBOARD_NAME = "Dirham Watch"
COLLECTION_NAME = "Dirham Watch"
DESCRIPTION = (
    "How the dirham moves against the euro and the dollar, compared with Moroccan consumer "
    "prices. Sources: Bank Al-Maghrib (exchange rates), HCP statistics database (CPI)."
)


def percent(*columns: str, decimals: int = 1) -> dict[str, Any]:
    return {
        json.dumps(["name", c]): {"number_style": "percent", "decimals": decimals} for c in columns
    }


# Each card: (name, display, sql, visualization_settings, (col, row, width, height)).
# Metabase dashboards are 24 columns wide.
CARDS = [
    (
        "Latest MAD per EUR",
        "scalar",
        """
        select mad_per_unit as "MAD per EUR"
        from staging.stg_fx_daily
        where currency_code = 'EUR'
        order by rate_date desc
        limit 1
        """,
        {"scalar.decimals": 4},
        (0, 0, 5, 4),
    ),
    (
        "Latest MAD per USD",
        "scalar",
        """
        select mad_per_unit as "MAD per USD"
        from staging.stg_fx_daily
        where currency_code = 'USD'
        order by rate_date desc
        limit 1
        """,
        {"scalar.decimals": 4},
        (5, 0, 5, 4),
    ),
    (
        "Latest inflation (year on year)",
        "scalar",
        """
        select inflation_yoy as "Inflation, year on year"
        from marts.mart_fx_vs_inflation
        where has_cpi
        order by report_month desc
        limit 1
        """,
        {"column_settings": percent("Inflation, year on year")},
        (10, 0, 5, 4),
    ),
    (
        "Data freshness",
        "table",
        """
        select
            dataset_label as "Dataset",
            case when is_stale then 'stale' else 'fresh' end as "Status",
            lag || ' ' || lag_unit as "Age",
            latest_period as "Latest period"
        from marts.data_freshness
        order by dataset
        """,
        {},
        (15, 0, 9, 4),
    ),
    (
        "Dirham vs consumer prices since 2017 (2017 = 100)",
        "line",
        """
        select
            report_month as "Month",
            eur_mad_index as "MAD per EUR",
            usd_mad_index as "MAD per USD",
            basket_index as "60/40 basket",
            cpi_index as "Consumer prices"
        from marts.mart_fx_vs_inflation
        order by report_month
        """,
        {
            "graph.dimensions": ["Month"],
            "graph.metrics": [
                "MAD per EUR",
                "MAD per USD",
                "60/40 basket",
                "Consumer prices",
            ],
            "graph.y_axis.title_text": "Index, 2017 average = 100",
            "graph.y_axis.unpin_from_zero": True,
            "graph.x_axis.title_text": "",
        },
        (0, 4, 24, 8),
    ),
    (
        "Year-on-year change: exchange rates vs inflation",
        "line",
        """
        select
            report_month as "Month",
            eur_mad_yoy_change as "MAD per EUR",
            usd_mad_yoy_change as "MAD per USD",
            inflation_yoy as "Inflation"
        from marts.mart_fx_vs_inflation
        where report_month >= date '2018-01-01'
        order by report_month
        """,
        {
            "graph.dimensions": ["Month"],
            "graph.metrics": ["MAD per EUR", "MAD per USD", "Inflation"],
            "graph.x_axis.title_text": "",
            "column_settings": percent("MAD per EUR", "MAD per USD", "Inflation"),
        },
        (0, 12, 24, 8),
    ),
    (
        "MAD per EUR and USD, monthly average",
        "line",
        """
        select
            rate_month as "Month",
            max(avg_mad_per_unit) filter (where currency_code = 'EUR') as "EUR",
            max(avg_mad_per_unit) filter (where currency_code = 'USD') as "USD"
        from marts.fct_fx_monthly
        where currency_code in ('EUR', 'USD')
        group by rate_month
        order by rate_month
        """,
        {
            "graph.dimensions": ["Month"],
            "graph.metrics": ["EUR", "USD"],
            "graph.x_axis.title_text": "",
            "graph.y_axis.title_text": "MAD",
            "graph.y_axis.unpin_from_zero": True,
        },
        (0, 20, 12, 8),
    ),
    (
        "MAD per EUR, daily, last 12 months",
        "line",
        """
        select rate_date as "Date", mad_per_unit as "MAD per EUR"
        from staging.stg_fx_daily
        where
            currency_code = 'EUR'
            and rate_date > (select max(rate_date) from staging.stg_fx_daily) - interval '1 year'
        order by rate_date
        """,
        {
            "graph.dimensions": ["Date"],
            "graph.metrics": ["MAD per EUR"],
            "graph.x_axis.title_text": "",
            "graph.y_axis.unpin_from_zero": True,
        },
        (12, 20, 12, 8),
    ),
    (
        "Inflation by product division, latest month",
        "row",
        """
        select
            initcap(group_label) as "Division",
            yoy_change as "Year on year"
        from marts.fct_cpi_yoy
        where
            is_national
            and group_level = 1
            and index_month = (select max(index_month) from marts.fct_cpi_yoy)
        order by yoy_change desc
        """,
        {
            "graph.dimensions": ["Division"],
            "graph.metrics": ["Year on year"],
            "column_settings": percent("Year on year"),
        },
        (0, 28, 12, 9),
    ),
    (
        "Food vs all-items inflation, national (year on year)",
        "line",
        """
        select
            report_month as "Month",
            inflation_yoy as "All items",
            food_inflation_yoy as "Food and non-alcoholic beverages"
        from marts.mart_fx_vs_inflation
        where has_cpi and inflation_yoy is not null
        order by report_month
        """,
        {
            "graph.dimensions": ["Month"],
            "graph.metrics": ["All items", "Food and non-alcoholic beverages"],
            "graph.x_axis.title_text": "",
            "column_settings": percent("All items", "Food and non-alcoholic beverages"),
        },
        (12, 28, 12, 9),
    ),
    (
        "Inflation by city, latest month",
        "row",
        """
        select city as "City", yoy_change as "Year on year"
        from marts.fct_cpi_yoy
        where
            group_code = 'GR'
            and index_month = (select max(index_month) from marts.fct_cpi_yoy)
        order by yoy_change desc
        """,
        {
            "graph.dimensions": ["City"],
            "graph.metrics": ["Year on year"],
            "column_settings": percent("Year on year"),
        },
        # Row charts sum the rows that do not fit the card height into "Other": 19
        # cities need this height.
        (0, 37, 24, 13),
    ),
]


def api(method: str, path: str, body: Any = None, session: str | None = None) -> Any:
    request = urllib.request.Request(
        f"{MB_URL}/api{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if session:
        request.add_header("X-Metabase-Session", session)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from None
    return json.loads(raw) if raw else None


def items(payload: Any) -> list[dict]:
    """Some list endpoints return a bare list, newer ones wrap it in {"data": [...]}."""
    return payload["data"] if isinstance(payload, dict) else payload


def wait_until_healthy(timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if api("GET", "/health").get("status") == "ok":
                return
        except (RuntimeError, OSError):
            pass
        if time.monotonic() > deadline:
            sys.exit(f"Metabase at {MB_URL} not healthy after {timeout_seconds}s")
        time.sleep(5)


def login() -> str:
    properties = api("GET", "/session/properties")
    if not properties.get("has-user-setup"):
        api(
            "POST",
            "/setup",
            {
                "token": properties["setup-token"],
                "user": {
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "first_name": "Dirham",
                    "last_name": "Watch",
                    "site_name": "Dirham Watch",
                },
                "prefs": {
                    "site_name": "Dirham Watch",
                    "site_locale": "en",
                    "allow_tracking": False,
                },
            },
        )
        print("Created the Metabase admin account")
    return api("POST", "/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["id"]


def ensure_database(session: str) -> int:
    details = {
        "host": os.environ.get("WAREHOUSE_HOST", "postgres"),
        "port": int(os.environ.get("WAREHOUSE_PORT", "5432")),
        "dbname": os.environ.get("WAREHOUSE_DB", "warehouse"),
        "user": os.environ.get("METABASE_READER_USER", "metabase_reader"),
        "password": os.environ["METABASE_READER_PASSWORD"],
        "ssl": False,
        "schema-filters-type": "inclusion",
        "schema-filters-patterns": "marts,staging",
    }
    for database in items(api("GET", "/database", session=session)):
        if database["name"] == DATABASE_NAME:
            api("PUT", f"/database/{database['id']}", {"details": details}, session)
            return database["id"]
    database = api(
        "POST",
        "/database",
        {
            "engine": "postgres",
            "name": DATABASE_NAME,
            "details": details,
            "is_full_sync": True,
        },
        session,
    )
    print(f"Connected the warehouse as database {database['id']}")
    return database["id"]


def ensure_collection(session: str) -> int:
    for collection in items(api("GET", "/collection", session=session)):
        if collection.get("name") == COLLECTION_NAME and not collection.get("archived"):
            return collection["id"]
    return api("POST", "/collection", {"name": COLLECTION_NAME}, session)["id"]


def ensure_cards(session: str, database_id: int, collection_id: int) -> list[tuple[int, tuple]]:
    existing = {
        card["name"]: card["id"]
        for card in items(api("GET", "/card?f=all", session=session))
        if card.get("collection_id") == collection_id and not card.get("archived")
    }
    placed = []
    for name, display, sql, settings, position in CARDS:
        body = {
            "name": name,
            "display": display,
            "collection_id": collection_id,
            "visualization_settings": settings,
            "dataset_query": {
                "type": "native",
                "database": database_id,
                "native": {"query": textwrap.dedent(sql).strip()},
            },
        }
        if name in existing:
            card_id = api("PUT", f"/card/{existing[name]}", body, session)["id"]
        else:
            card_id = api("POST", "/card", body, session)["id"]
        placed.append((card_id, position))
    return placed


def ensure_dashboard(session: str, collection_id: int, cards: list[tuple[int, tuple]]) -> int:
    dashboard_id = next(
        (
            d["id"]
            for d in items(api("GET", "/dashboard", session=session))
            if d["name"] == DASHBOARD_NAME and not d.get("archived")
        ),
        None,
    )
    if dashboard_id is None:
        dashboard_id = api(
            "POST",
            "/dashboard",
            {"name": DASHBOARD_NAME, "collection_id": collection_id, "description": DESCRIPTION},
            session,
        )["id"]
    dashcards = [
        {
            "id": -(i + 1),
            "card_id": card_id,
            "col": col,
            "row": row,
            "size_x": width,
            "size_y": height,
            "parameter_mappings": [],
            "visualization_settings": {},
        }
        for i, (card_id, (col, row, width, height)) in enumerate(cards)
    ]
    api(
        "PUT",
        f"/dashboard/{dashboard_id}",
        {"description": DESCRIPTION, "dashcards": dashcards},
        session,
    )
    return dashboard_id


def check_cards(session: str, cards: list[tuple[int, tuple]]) -> int:
    """Run every dashboard question; returns the number that failed or came back empty."""
    failures = 0
    for card_id, _ in cards:
        card = api("GET", f"/card/{card_id}", session=session)
        try:
            result = api("POST", f"/card/{card_id}/query", {}, session)
            rows = len(result.get("data", {}).get("rows", []))
            ok = result.get("status") == "completed" and rows > 0
            detail = f"{rows} rows"
        except RuntimeError as exc:
            ok, detail = False, str(exc)[:200]
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {card['name']}: {detail}")
    return failures


def main() -> None:
    wait_until_healthy()
    session = login()
    database_id = ensure_database(session)
    collection_id = ensure_collection(session)
    cards = ensure_cards(session, database_id, collection_id)
    dashboard_id = ensure_dashboard(session, collection_id, cards)
    print(f"Dashboard ready: {PUBLIC_URL}/dashboard/{dashboard_id} ({len(cards)} cards)")
    # `--check` runs every question once the warehouse is loaded (not at first start,
    # when the backfill may still be running).
    if "--check" in sys.argv[1:] and check_cards(session, cards):
        sys.exit("Some dashboard questions failed")


if __name__ == "__main__":
    main()
