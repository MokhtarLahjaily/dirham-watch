import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import responses

from dirham_watch.cpi import CpiRow, HcpClient, parse_indicator, parse_period

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def indicator() -> dict:
    """A real slice of HCP's monthly CPI (I4166): 2 cities, 3 product groups, 3 months."""
    return json.loads((FIXTURES / "hcp_bds_I4166_sample.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("label", "expected"),
    [("2026M5", date(2026, 5, 1)), ("2017M1", date(2017, 1, 1)), (" 2024M12 ", date(2024, 12, 1))],
)
def test_parse_period(label, expected):
    assert parse_period(label) == expected


@pytest.mark.parametrize("label", ["2026M13", "2026M0", "2026-05", "2026", "2026Q1"])
def test_parse_period_fails_loudly_on_unknown_formats(label):
    with pytest.raises(ValueError, match="Unrecognised"):
        parse_period(label)


def test_parse_indicator_melts_every_cell(indicator):
    rows = list(parse_indicator(indicator))

    assert len(rows) == 18  # 2 cities x 3 groups x 3 months
    assert {r.city for r in rows} == {"National", "Fès"}
    assert {r.product_group.split(")")[0] + ")" for r in rows} == {"(GR)", "(01)", "(0111)"}
    assert {r.period_month for r in rows} == {date(2026, 5, 1), date(2026, 4, 1), date(2025, 5, 1)}
    headline = next(
        r for r in rows
        if r.city == "National" and r.product_group == "(GR) GENERAL" and r.period_label == "2026M5"
    )  # fmt: skip
    assert headline == CpiRow("National", "(GR) GENERAL", "2026M5", date(2026, 5, 1), "120.4")


def test_parse_indicator_skips_empty_cells(indicator):
    key = next(iter(indicator["data"]))
    indicator["data"][key] = {"value": None, "footNote": None}
    assert len(list(parse_indicator(indicator))) == 17


def test_parse_indicator_refuses_a_shut_off_indicator(indicator):
    indicator.update(isShutOff=True, shutOffComment="maintenance")
    with pytest.raises(RuntimeError, match="maintenance"):
        list(parse_indicator(indicator))


def test_parse_indicator_checks_the_dimensions(indicator):
    indicator["dimensions"][0]["label"] = "Régions"
    with pytest.raises(ValueError, match="Villes"):
        list(parse_indicator(indicator))


@responses.activate
def test_client_reads_the_update_date(indicator):
    responses.get("https://hcp.test/api/v1/indicators/I4166", json=indicator)

    resource, payload = HcpClient("https://hcp.test/api/v1/").fetch_indicator("I4166")

    assert payload["code"] == "I4166"
    assert resource.dataset_id == "I4166"
    assert resource.resource_id == "https://hcp.test/api/v1/indicators/I4166"
    assert resource.last_modified == datetime.fromtimestamp(indicator["updatingDate"] / 1000, UTC)
    assert resource.last_modified.date() == date(2026, 6, 22)
