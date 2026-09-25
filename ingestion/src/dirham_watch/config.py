"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

FX_SOURCES = ("auto", "bam", "frankfurter")

# Currencies fetched from the Frankfurter mirror: all 30 that Bank Al-Maghrib quotes, so
# history loaded through the mirror matches what the BAM API returns every day.
DEFAULT_FX_CURRENCIES = (
    "AED", "AUD", "BHD", "BRL", "CAD", "CHF", "CNY", "DKK", "DZD", "EGP",
    "EUR", "GBP", "GIP", "INR", "JOD", "JPY", "KWD", "LYD", "MRO", "NOK",
    "OMR", "QAR", "RUB", "SAR", "SEK", "TND", "TRY", "USD", "XOF", "ZAR",
)  # fmt: skip


def _fx_source(env: dict[str, str], name: str, default: str) -> str:
    value = env.get(name, default).strip().lower()
    if value not in FX_SOURCES:
        raise ValueError(f"{name} must be one of {FX_SOURCES}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    warehouse_host: str = "localhost"
    warehouse_port: int = 5433
    warehouse_db: str = "warehouse"
    warehouse_user: str = "dirham"
    warehouse_password: str = ""
    bam_api_key: str | None = None
    # The BAM API allows 5 calls per minute per subscription (HTTP 429 beyond that).
    bam_requests_per_minute: int = 5
    fx_source: str = "auto"
    # One BAM call per business day at 5 per minute makes a 2010 backfill take ~15 hours;
    # the mirror serves the same BAM series in one request per currency.
    fx_backfill_source: str = "frankfurter"
    fx_currencies: tuple[str, ...] = DEFAULT_FX_CURRENCIES
    fx_backfill_start: date = date(2010, 1, 1)
    # HCP statistics database API; I4166 = monthly CPI, base 100 = 2017, by city and group.
    hcp_api_url: str = "https://bds.hcp.ma/api/v1"
    cpi_indicator: str = "I4166"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        currencies = env.get("FX_CURRENCIES")
        return cls(
            warehouse_host=env.get("WAREHOUSE_HOST", cls.warehouse_host),
            warehouse_port=int(env.get("WAREHOUSE_PORT", cls.warehouse_port)),
            warehouse_db=env.get("WAREHOUSE_DB", cls.warehouse_db),
            warehouse_user=env.get("WAREHOUSE_USER", cls.warehouse_user),
            warehouse_password=env.get("WAREHOUSE_PASSWORD", ""),
            bam_api_key=env.get("BAM_API_KEY") or None,
            bam_requests_per_minute=int(
                env.get("BAM_REQUESTS_PER_MINUTE", cls.bam_requests_per_minute)
            ),
            fx_source=_fx_source(env, "FX_SOURCE", cls.fx_source),
            fx_backfill_source=_fx_source(env, "FX_BACKFILL_SOURCE", cls.fx_backfill_source),
            fx_currencies=(
                tuple(c.strip().upper() for c in currencies.split(",") if c.strip())
                if currencies
                else DEFAULT_FX_CURRENCIES
            ),
            fx_backfill_start=date.fromisoformat(
                env.get("FX_BACKFILL_START", cls.fx_backfill_start.isoformat())
            ),
            hcp_api_url=env.get("HCP_API_URL", cls.hcp_api_url).rstrip("/"),
            cpi_indicator=env.get("CPI_INDICATOR", cls.cpi_indicator),
        )

    def resolved_fx_source(self, override: str | None = None) -> str:
        """`auto` means the BAM API when a key is configured, the Frankfurter mirror otherwise."""
        source = (override or self.fx_source).lower()
        if source == "auto":
            return "bam" if self.bam_api_key else "frankfurter"
        if source == "bam" and not self.bam_api_key:
            raise ValueError("FX source 'bam' needs BAM_API_KEY")
        return source

    def conninfo(self) -> dict[str, str | int]:
        return {
            "host": self.warehouse_host,
            "port": self.warehouse_port,
            "dbname": self.warehouse_db,
            "user": self.warehouse_user,
            "password": self.warehouse_password,
        }
