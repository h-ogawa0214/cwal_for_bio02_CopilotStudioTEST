from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .textutil import normalize_whitespace

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "n_cid",
}

_TITLE_BOILERPLATE = re.compile(
    r"(に関するお知らせ|のお知らせ|について|のお知らせです)$"
)
_PUNCT = re.compile(r"[「」『』【】\[\]（）()・、。,.!！?？：:；;〜～\-\s　]+")


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query, doseq=True),
            "",
        )
    )


def normalize_title_key(title: str) -> str:
    text = normalize_whitespace(title)
    text = _TITLE_BOILERPLATE.sub("", text)
    text = _PUNCT.sub("", text)
    return text.casefold()


def release_fingerprint(
    company: str,
    published_on: date | str | None,
    title: str,
) -> str:
    """Stable soft key for the same disclosure across URLs / crawl runs."""
    title_key = normalize_title_key(title)
    if isinstance(published_on, date):
        day = published_on.isoformat()
    else:
        day = str(published_on or "").strip()
    return f"{normalize_whitespace(company)}|{day}|{title_key}"


def content_hash(text: str) -> str:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def titles_likely_same(left: str, right: str) -> bool:
    a = normalize_title_key(left)
    b = normalize_title_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 12:
        return False
    return shorter in longer
