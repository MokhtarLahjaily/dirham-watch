"""Command line: `dirham-watch {init-db,fx,cpi,export-rates}`."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from dirham_watch import pipeline
from dirham_watch.config import FX_SOURCES, Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dirham-watch", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the raw schema and tables")

    fx = sub.add_parser("fx", help="load daily exchange rates into raw.fx_rates")
    fx.add_argument(
        "--start",
        type=date.fromisoformat,
        help="first date (default: --lookback-days before --end)",
    )
    fx.add_argument(
        "--end", type=date.fromisoformat, default=date.today(), help="last date (default: today)"
    )
    fx.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="re-fetch window when --start is omitted (default: 7)",
    )
    fx.add_argument(
        "--backfill",
        action="store_true",
        help="load from FX_BACKFILL_START through FX_BACKFILL_SOURCE (default: the mirror)",
    )
    fx.add_argument("--source", choices=FX_SOURCES, help="override FX_SOURCE")

    cpi = sub.add_parser("cpi", help="load the HCP CPI into raw.cpi_index")
    cpi.add_argument("--force", action="store_true", help="reload even if unchanged")

    export = sub.add_parser("export-rates", help="write the latest rates to a JSON file")
    export.add_argument("--out", type=Path, default=Path("exports/rates.json"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()

    if args.command == "init-db":
        pipeline.init_db(settings)
        result = {"status": "ok"}
    elif args.command == "fx":
        if args.backfill:
            start = settings.fx_backfill_start
            source = args.source or settings.fx_backfill_source
        else:
            start = args.start or args.end - timedelta(days=args.lookback_days)
            source = args.source
        result = pipeline.load_fx(settings, start, args.end, source=source)
    elif args.command == "cpi":
        result = pipeline.load_cpi(settings, force=args.force)
    else:
        result = pipeline.export_rates(settings, args.out)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
