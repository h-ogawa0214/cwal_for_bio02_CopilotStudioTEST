from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

_JP_DATE_RE = re.compile(
    r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
)
_SLASH_DATE_RE = re.compile(r"(?P<y>20\d{2})[./\-](?P<m>\d{1,2})[./\-](?P<d>\d{1,2})")
_ISO_DATETIME_RE = re.compile(r"^(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})T")


def parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None

    m = _JP_DATE_RE.search(text)
    if m:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    m = _SLASH_DATE_RE.search(text)
    if m:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))

    # Do not use fuzzy parsing here. It interpreted fiscal-year text such as
    # "2026年3月期" as July 3, 2026 by filling missing fields from today's date.
    m = _ISO_DATETIME_RE.search(text)
    if m:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    return None


def normalize_whitespace(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    # PDF line wrapping often inserts spaces between Japanese characters.
    return re.sub(
        r"(?<=[ぁ-んァ-ン一-龥々〆ヵヶー])\s+(?=[ぁ-んァ-ン一-龥々〆ヵヶー])",
        "",
        cleaned,
    )


def first_paragraph(text: str, limit: int = 2000) -> str:
    if not text:
        return ""
    blocks = [
        normalize_whitespace(block)
        for block in re.split(r"(?:\r?\n\s*){2,}", text)
        if normalize_whitespace(block)
    ]
    paragraph = blocks[0] if blocks else normalize_whitespace(text)
    if len(paragraph) > limit:
        return paragraph[: limit - 1] + "…"
    return paragraph
