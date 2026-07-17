from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class Company(BaseModel):
    name: str
    list_url: str
    enabled: bool = True
    source_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class RawRelease(BaseModel):
    company: str
    title: str
    url: str
    published_on: date | None = None
    summary: str = ""
    source_type: str = ""
    reference_url: str = ""


class CuratedRelease(BaseModel):
    published_on: date
    company: str
    title: str
    paragraph: str
    url: str
    keep: bool
    reason: str = ""
    original_title: str = ""
    reference_url: str = ""
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
