from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Json,
    model_validator,
)

from struudel.models.poll import PollResponseMode, PollStatus, PollVisibility
from struudel.models.poll_option import PollOptionType
from struudel.models.poll_response import PollResponseStatus
from struudel.timezones import to_utc


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _empty_to_empty_list(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return "[]"
    return value


def _normalize_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return to_utc(value)


OptionalStr = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptionalDate = Annotated[date | None, BeforeValidator(_empty_to_none)]
OptionalDateTime = Annotated[
    datetime | None,
    BeforeValidator(_empty_to_none),
    AfterValidator(_normalize_to_utc),
]


class PollOptionData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    type: PollOptionType
    date_value: OptionalDate = None
    datetime_value: OptionalDateTime = None
    text_value: OptionalStr = None

    @model_validator(mode="after")
    def _exactly_one_value(self) -> PollOptionData:
        values = {
            PollOptionType.DATE: self.date_value,
            PollOptionType.DATETIME: self.datetime_value,
            PollOptionType.TEXT: self.text_value,
        }
        if values[self.type] is None:
            raise ValueError(f"value for {self.type.value} option is missing")
        other_fields = [k for k in values if k != self.type]
        if any(values[k] is not None for k in other_fields):
            raise ValueError(f"{self.type.value} option must only set its matching value field")
        return self


class PollForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: str = Field(min_length=1, max_length=200)
    description_short: OptionalStr = None
    description_long: OptionalStr = None

    status: PollStatus = PollStatus.DRAFT
    visibility: PollVisibility = PollVisibility.PRIVATE
    response_mode: PollResponseMode = PollResponseMode.YES_NO_MAYBE

    is_mandatory: bool = False
    allow_custom_options: bool = False
    allow_edit_responses: bool = False
    auto_delete: bool = True
    allow_guests: bool = False
    max_guests: Annotated[int | None, BeforeValidator(_empty_to_none)] = None

    notify_owner_on_response: bool = False
    notify_audience_on_close: bool = True

    anonymous_votes: bool = False
    hide_results_until_close: bool = False
    max_yes_choices: Annotated[int | None, BeforeValidator(_empty_to_none)] = None

    edit_responses_until: OptionalDateTime = None
    starts_at: OptionalDateTime = None
    ends_at: OptionalDateTime = None

    options: Annotated[
        Json[list[PollOptionData]],
        BeforeValidator(_empty_to_empty_list),
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_date_window(self) -> PollForm:
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (
            self.allow_edit_responses
            and self.edit_responses_until
            and self.ends_at
            and self.edit_responses_until > self.ends_at
        ):
            raise ValueError("edit_responses_until cannot be after ends_at")
        return self

    @model_validator(mode="after")
    def _check_public_not_mandatory(self) -> PollForm:
        if self.visibility == PollVisibility.PUBLIC and self.is_mandatory:
            raise ValueError("public polls cannot be mandatory")
        return self

    @model_validator(mode="after")
    def _check_guests(self) -> PollForm:
        if not self.allow_guests:
            self.max_guests = None
            return self
        if self.max_guests is not None and not (1 <= self.max_guests <= 9):
            raise ValueError("max_guests must be between 1 and 9")
        return self

    @model_validator(mode="after")
    def _check_max_yes_choices(self) -> PollForm:
        if self.response_mode != PollResponseMode.MULTI_CHOICE:
            self.max_yes_choices = None
            return self
        if self.max_yes_choices is not None and not (1 <= self.max_yes_choices <= 50):
            raise ValueError("max_yes_choices must be between 1 and 50")
        return self


class AudienceMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int


class AudienceForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    users: Annotated[
        Json[list[AudienceMember]],
        BeforeValidator(_empty_to_empty_list),
    ] = Field(default_factory=list)
    groups: Annotated[
        Json[list[AudienceMember]],
        BeforeValidator(_empty_to_empty_list),
    ] = Field(default_factory=list)


class VoteItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    option_id: int
    status: PollResponseStatus
    guest_count: int = Field(default=0, ge=0)


class VoteForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    comment: OptionalStr = None
    votes: Annotated[
        Json[list[VoteItem]],
        BeforeValidator(_empty_to_empty_list),
    ] = Field(default_factory=list)
