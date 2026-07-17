from __future__ import annotations

import re
from datetime import date

from .textutil import normalize_whitespace


def release_fingerprint(
    company: str,
    published_on: date | str | None,
    title: str,
) -> str:
    """Stable soft key for the same disclosure across URLs / crawl runs."""
    title_key = re.sub(r"\s+", "", normalize_whitespace(title))
    if isinstance(published_on, date):
        day = published_on.isoformat()
    else:
        day = str(published_on or "").strip()
    return f"{normalize_whitespace(company)}|{day}|{title_key}"
