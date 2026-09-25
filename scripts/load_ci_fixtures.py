"""Load ci/fixtures/*.csv into the raw schema, replacing its contents.

Used by CI before `dbt build`. Point the WAREHOUSE_* variables at a throwaway database:
this truncates raw.fx_rates and raw.cpi_index.
"""

from __future__ import annotations

import csv
from pathlib import Path

from psycopg import sql

from dirham_watch import db
from dirham_watch.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "ci" / "fixtures"
TABLES = {"fx_rates": "raw_fx_rates.csv", "cpi_index": "raw_cpi_index.csv"}


def main() -> None:
    with db.connect(Settings.from_env()) as conn:
        db.init_schema(conn)
        with conn.transaction():
            for table, filename in TABLES.items():
                with (FIXTURES / filename).open(newline="", encoding="utf-8") as handle:
                    reader = csv.reader(handle)
                    columns = next(reader)
                    target = sql.Identifier("raw", table)
                    conn.execute(sql.SQL("truncate {}").format(target))
                    copy_sql = sql.SQL("copy {} ({}) from stdin").format(
                        target, sql.SQL(", ").join(map(sql.Identifier, columns))
                    )
                    with conn.cursor().copy(copy_sql) as copy:
                        count = 0
                        for row in reader:
                            copy.write_row([value or None for value in row])
                            count += 1
                print(f"raw.{table}: {count} rows")


if __name__ == "__main__":
    main()
