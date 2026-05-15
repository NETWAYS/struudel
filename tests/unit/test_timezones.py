from datetime import datetime
from zoneinfo import ZoneInfo

from struudel.timezones import UTC, app_tz, to_local, to_utc

BERLIN = ZoneInfo("Europe/Berlin")


def test_app_tz_default_is_europe_berlin() -> None:
    assert str(app_tz()) == "Europe/Berlin"


def test_to_utc_naive_interpreted_as_app_tz() -> None:
    naive = datetime(2026, 7, 15, 14, 0)
    result = to_utc(naive)
    assert result.tzinfo == UTC
    assert result == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_to_utc_aware_passes_through() -> None:
    aware = datetime(2026, 7, 15, 14, 0, tzinfo=BERLIN)
    result = to_utc(aware)
    assert result == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_to_utc_already_utc_unchanged() -> None:
    aware_utc = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert to_utc(aware_utc) == aware_utc


def test_to_local_converts_utc_to_app_tz() -> None:
    utc = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    local = to_local(utc)
    assert local.tzinfo is not None
    assert local.tzinfo.utcoffset(local) == BERLIN.utcoffset(local)
    assert local.hour == 14


def test_roundtrip_preserves_instant() -> None:
    naive = datetime(2026, 7, 15, 14, 0)
    assert to_local(to_utc(naive)).replace(tzinfo=None) == naive


def test_winter_offset_is_one_hour() -> None:
    naive = datetime(2026, 1, 15, 14, 0)
    assert to_utc(naive) == datetime(2026, 1, 15, 13, 0, tzinfo=UTC)


def test_dst_transition_spring_forward() -> None:
    """2026-03-29 02:00 Europe/Berlin springs forward to 03:00. 02:30 doesn't exist."""
    naive_pre = datetime(2026, 3, 29, 1, 30)
    naive_post = datetime(2026, 3, 29, 3, 30)
    assert to_utc(naive_pre) == datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    assert to_utc(naive_post) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)


def test_to_local_naive_treated_as_utc() -> None:
    naive = datetime(2026, 7, 15, 12, 0)
    local = to_local(naive)
    assert local.hour == 14
