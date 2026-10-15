from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from struudel.blueprints.polls.forms import PollForm, PollOptionData
from struudel.models.poll_option import PollOptionType
from struudel.timezones import UTC

BERLIN = ZoneInfo("Europe/Berlin")


def _base_form(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "title": "Test",
        "options": "[]",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# OptionalDateTime — empty/naive/aware handling
# ---------------------------------------------------------------------------


def test_empty_string_becomes_none() -> None:
    form = PollForm.model_validate(_base_form(starts_at=""))
    assert form.starts_at is None


def test_naive_string_normalized_to_utc() -> None:
    form = PollForm.model_validate(_base_form(starts_at="2026-07-15T14:00"))
    assert form.starts_at == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_aware_string_with_offset_kept_as_utc() -> None:
    form = PollForm.model_validate(_base_form(starts_at="2026-07-15T14:00+02:00"))
    assert form.starts_at == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# PollOptionData._exactly_one_value
# ---------------------------------------------------------------------------


def test_text_option_requires_text_value() -> None:
    PollOptionData.model_validate({"type": "TEXT", "text_value": "Foo"})
    with pytest.raises(ValidationError):
        PollOptionData.model_validate({"type": "TEXT"})


def test_text_option_rejects_other_value_fields() -> None:
    with pytest.raises(ValidationError):
        PollOptionData.model_validate(
            {"type": "TEXT", "text_value": "Foo", "date_value": "2026-01-01"}
        )


def test_datetime_option_requires_datetime_value() -> None:
    opt = PollOptionData.model_validate({"type": "DATETIME", "datetime_value": "2026-07-15T14:00"})
    assert opt.type == PollOptionType.DATETIME
    assert opt.datetime_value == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_date_option_requires_date_value() -> None:
    opt = PollOptionData.model_validate({"type": "DATE", "date_value": "2026-07-15"})
    assert opt.type == PollOptionType.DATE
    assert opt.date_value is not None
    assert opt.date_value.isoformat() == "2026-07-15"


# ---------------------------------------------------------------------------
# PollForm._check_date_window
# ---------------------------------------------------------------------------


def test_ends_at_must_be_after_starts_at() -> None:
    with pytest.raises(ValidationError) as exc:
        PollForm.model_validate(
            _base_form(starts_at="2026-07-15T14:00", ends_at="2026-07-15T13:00")
        )
    assert "ends_at must be after starts_at" in str(exc.value)


def test_ends_at_equal_to_starts_at_rejected() -> None:
    with pytest.raises(ValidationError):
        PollForm.model_validate(
            _base_form(starts_at="2026-07-15T14:00", ends_at="2026-07-15T14:00")
        )


def test_starts_at_only_is_fine() -> None:
    form = PollForm.model_validate(_base_form(starts_at="2026-07-15T14:00"))
    assert form.ends_at is None


# ---------------------------------------------------------------------------
# PollForm._check_option_group_references
# ---------------------------------------------------------------------------


def test_duplicate_group_client_keys_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        PollForm.model_validate(
            _base_form(
                groups='[{"client_key": "new-2", "name": "A"},'
                ' {"client_key": "new-2", "name": "B"}]'
            )
        )
    assert "unique client keys" in str(exc.value)


def test_option_referencing_unknown_group_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        PollForm.model_validate(
            _base_form(
                options='[{"type": "TEXT", "text_value": "A", "group_client_key": "new-1"}]',
                groups='[{"client_key": "new-2", "name": "G"}]',
            )
        )
    assert "unknown group 'new-1'" in str(exc.value)
