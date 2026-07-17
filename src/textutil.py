from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from dateutil import parser as date_parser


_JP_DATE_RE = re.compile(
    r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
)
_SLASH_DATE_RE = re.compile(r"(?P<y>20\d{2})[./\-](?P<m>\d{1,2})[./\-](?P<d>\d{1,2})")


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

    try:
        return date_parser.parse(text, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def first_paragraph(text: str, limit: int = 500) -> str:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return ""
    # Prefer Japanese/English sentence break
    parts = re.split(r"(?<=。)\s+|(?<=\.)\s+", cleaned)
    paragraph = parts[0] if parts else cleaned
    if len(paragraph) > limit:
        return paragraph[: limit - 1] + "…"
    return paragraph
