from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Company, RawRelease
from ..textutil import normalize_whitespace
from .base import Extractor

logger = logging.getLogger("pr-disclosure-curator")

TDNET_BASE = "https://www.release.tdnet.info/inbs/"
_TOTAL_RE = re.compile(r"全\s*(\d+)\s*件")
_PAGE_SIZE = 100


def normalize_tdnet_code(stock_code: str) -> str:
    """Normalize a TSE code to TDnet's 5-character issuer code (e.g. 4503 -> 45030)."""
    code = (stock_code or "").strip().upper().replace(" ", "")
    if not code:
        return ""
    if len(code) == 4 and code.isalnum():
        return f"{code}0"
    return code


def companies_by_tdnet_code(companies: list[Company]) -> dict[str, Company]:
    mapping: dict[str, Company] = {}
    for company in companies:
        code = normalize_tdnet_code(company.stock_code)
        if code:
            mapping[code] = company
    return mapping


def parse_tdnet_list_html(
    html: str,
    *,
    published_on: date,
    code_map: dict[str, Company],
    base_url: str = TDNET_BASE,
) -> list[RawRelease]:
    soup = BeautifulSoup(html, "lxml")
    results: list[RawRelease] = []
    seen_urls: set[str] = set()

    for code_td in soup.select("td.kjCode"):
        code = code_td.get_text(strip=True)
        company = code_map.get(code)
        if not company:
            continue
        row = code_td.find_parent("tr")
        if row is None:
            continue
        title_anchor = row.select_one("td.kjTitle a[href]")
        if title_anchor is None:
            continue
        title = normalize_whitespace(title_anchor.get_text(" ", strip=True))
        href = (title_anchor.get("href") or "").strip()
        if not title or not href:
            continue
        url = urljoin(base_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        results.append(
            RawRelease(
                company=company.name,
                title=title,
                url=url,
                published_on=published_on,
                summary="",
                source_type=TdnetExtractor.source_type,
                reference_url="",
                crawl_mode=company.crawl_mode,
            )
        )
    return results


def _total_count(html: str) -> int:
    match = _TOTAL_RE.search(html)
    return int(match.group(1)) if match else 0


def list_url_for(day: date, page: int = 1) -> str:
    return urljoin(TDNET_BASE, f"I_list_{page:03d}_{day.strftime('%Y%m%d')}.html")


class TdnetExtractor(Extractor):
    """Per-company Extractor shim. Prefer fetch_tdnet_releases() for aggregate runs."""

    source_type = "tdnet"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        code = normalize_tdnet_code(company.stock_code)
        if not code:
            raise ValueError(f"{company.name}: stock_code is required for tdnet")
        return fetch_tdnet_releases(
            [company],
            self.http,
            lookback_days=max(1, min(limit, 14)),
            max_items_per_company=limit,
        )


def fetch_tdnet_releases(
    companies: list[Company],
    http,
    *,
    lookback_days: int,
    max_items_per_company: int,
    today: date | None = None,
) -> list[RawRelease]:
    """Fetch recent TDnet disclosures once, filtered to companies with stock_code."""
    code_map = companies_by_tdnet_code(companies)
    if not code_map:
        return []

    end = today or date.today()
    start = end - timedelta(days=max(1, lookback_days) - 1)
    per_company: dict[str, list[RawRelease]] = {c.name: [] for c in code_map.values()}

    day = end
    while day >= start:
        page = 1
        total = None
        while True:
            url = list_url_for(day, page)
            try:
                html = http.get_text(url, referer=TDNET_BASE)
            except Exception:
                if page == 1:
                    logger.info("TDnet: no list for %s (page %s)", day.isoformat(), page)
                break

            if total is None:
                total = _total_count(html)
            items = parse_tdnet_list_html(html, published_on=day, code_map=code_map)
            for item in items:
                bucket = per_company.setdefault(item.company, [])
                if len(bucket) >= max_items_per_company:
                    continue
                if any(existing.url == item.url for existing in bucket):
                    continue
                bucket.append(item)

            if total is None or total == 0 or page * _PAGE_SIZE >= total:
                break
            page += 1

        day -= timedelta(days=1)

    results: list[RawRelease] = []
    for company_name in sorted(per_company):
        results.extend(per_company[company_name])
    logger.info(
        "TDnet: matched %s disclosures across %s issuers (%s days)",
        len(results),
        len(code_map),
        lookback_days,
    )
    return results
