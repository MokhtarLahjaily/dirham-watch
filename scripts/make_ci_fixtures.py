"""Write the CI fixtures (ci/fixtures/*.csv) from a loaded warehouse.

The fixtures are a small, real slice of the raw tables, so `dbt build` in CI runs on the
same data shapes as production without calling the sources:

* FX: EUR and USD from 2016-01-01 to 2026-03-31 (Frankfurter mirror of BAM), plus the
  recorded BAM API response for 2026-03-26, which repeats every currency, to exercise
  deduplication and the BAM-over-mirror priority.
* CPI (HCP statistics database): all items and the 12 divisions for National, Casablanca
  and Rabat, over the same months as the FX slice.

Usage: WAREHOUSE_* variables set, then `python scripts/make_ci_fixtures.py`.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from dirham_watch import db
from dirham_watch.config import Settings
from dirham_watch.fx import parse_bam

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ci" / "fixtures"
BAM_RESPONSE = ROOT / "ingestion" / "tests" / "fixtures" / "bam_cours_virement_2026-03-26.json"

FX_COLUMNS = ["source", "rate_date", "currency", "unit", "mid_rate", "bid_rate", "ask_rate",
              "payload"]  # fmt: skip
CPI_COLUMNS = ["city", "product_group", "period_label", "period_month", "index_value",
               "dataset_id", "resource_id", "resource_last_modified"]  # fmt: skip


def write(path: Path, columns: list[str], rows) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
    return count


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with db.connect(Settings.from_env()) as conn:
        fx = conn.execute(
            """
            select source, rate_date, currency, unit, mid_rate, bid_rate, ask_rate, payload::text
            from raw.fx_rates
            where source = 'frankfurter' and currency in ('EUR', 'USD')
              and rate_date between '2016-01-01' and '2026-03-31'
            order by rate_date, currency
            """
        ).fetchall()
        cpi = conn.execute(
            """
            select city, product_group, period_label, period_month, index_value,
                   dataset_id, resource_id, resource_last_modified
            from raw.cpi_index
            where city in ('National', 'Casablanca', 'Rabat')
              and product_group ~ '^\\((GR|[0-9]{2})\\) '
              and period_month <= '2026-03-01'
            order by city, product_group, period_month
            """
        ).fetchall()

    bam = [
        (r.source, r.rate_date, r.currency, r.unit, r.mid_rate, r.bid_rate, r.ask_rate,
         json.dumps(r.payload))
        for r in parse_bam(json.loads(BAM_RESPONSE.read_text()))
        if r.rate_date == date(2026, 3, 26)
    ]  # fmt: skip

    n_fx = write(OUT / "raw_fx_rates.csv", FX_COLUMNS, [*fx, *bam])
    n_cpi = write(OUT / "raw_cpi_index.csv", CPI_COLUMNS, cpi)
    print(f"raw_fx_rates.csv: {n_fx} rows ({len(bam)} from the BAM API)")
    print(f"raw_cpi_index.csv: {n_cpi} rows")


if __name__ == "__main__":
    main()
