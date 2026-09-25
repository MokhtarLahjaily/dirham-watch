from datetime import date

import pytest

from dirham_watch.config import DEFAULT_FX_CURRENCIES, Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings.fx_source == "auto"
    assert settings.fx_backfill_source == "frankfurter"
    assert settings.bam_requests_per_minute == 5
    assert settings.fx_currencies == DEFAULT_FX_CURRENCIES
    assert len(DEFAULT_FX_CURRENCIES) == 30 and {"EUR", "USD", "JPY"} <= set(DEFAULT_FX_CURRENCIES)
    assert settings.fx_backfill_start == date(2010, 1, 1)


def test_auto_source_uses_bam_only_with_a_key():
    assert Settings.from_env({}).resolved_fx_source() == "frankfurter"
    assert Settings.from_env({"BAM_API_KEY": "k"}).resolved_fx_source() == "bam"


def test_forcing_bam_without_a_key_fails():
    with pytest.raises(ValueError, match="BAM_API_KEY"):
        Settings.from_env({"FX_SOURCE": "bam"}).resolved_fx_source()


def test_override_beats_environment():
    settings = Settings.from_env({"BAM_API_KEY": "k"})
    assert settings.resolved_fx_source("frankfurter") == "frankfurter"


def test_env_parsing():
    settings = Settings.from_env(
        {
            "FX_SOURCE": "Frankfurter",
            "FX_CURRENCIES": "eur, usd,,gbp",
            "FX_BACKFILL_START": "2015-01-01",
            "WAREHOUSE_PORT": "5432",
            "HCP_API_URL": "https://bds.hcp.ma/api/v1/",
            "CPI_INDICATOR": "I3981",
        }
    )
    assert settings.fx_source == "frankfurter"
    assert settings.fx_currencies == ("EUR", "USD", "GBP")
    assert settings.fx_backfill_start == date(2015, 1, 1)
    assert settings.warehouse_port == 5432
    assert settings.hcp_api_url == "https://bds.hcp.ma/api/v1"
    assert settings.cpi_indicator == "I3981"


@pytest.mark.parametrize("name", ["FX_SOURCE", "FX_BACKFILL_SOURCE"])
def test_unknown_source_is_rejected(name):
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: "ecb"})


def test_backfill_source_and_rate_limit_are_configurable():
    settings = Settings.from_env({"FX_BACKFILL_SOURCE": "BAM", "BAM_REQUESTS_PER_MINUTE": "10"})
    assert settings.fx_backfill_source == "bam"
    assert settings.bam_requests_per_minute == 10
