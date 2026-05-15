from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GroupEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: int
    name: str = Field(min_length=1, max_length=200)
    hidden: bool = False
