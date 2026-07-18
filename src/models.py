from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CrawlMode = Literal["live", "shadow"]


class Company(BaseModel):
    name: str
    list_url: str
    enabled: bool = True
    source_type: str
    stock_code: str = ""
    crawl_mode: CrawlMode = "live"
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
    crawl_mode: CrawlMode = "live"


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
    source_type: str = ""
    crawl_mode: CrawlMode = "live"


class DecisionRecord(BaseModel):
    decided_at: datetime
    company: str
    published_on: str = ""
    title: str
    url: str
    canonical_url: str = ""
    fingerprint: str = ""
    content_hash: str = ""
    decision: str
    reason: str = ""
    source_type: str = ""
    model: str = ""
    criteria_version: str = ""
