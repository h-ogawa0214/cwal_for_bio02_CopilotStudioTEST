from __future__ import annotations

import logging
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import Company, RawRelease
from ..textutil import normalize_whitespace, parse_date
from .base import Extractor

logger = logging.getLogger("pr-disclosure-curator")

PRTIMES_BASE = "https://prtimes.jp"
_KEYWORD_URL = "https://prtimes.jp/topics/keywords/{keyword}"

# Keyword tags that map to the magazine's 医薬（動物医薬含む）・創薬・バイオテクノロジー focus.
DEFAULT_KEYWORDS = ["創薬", "バイオテクノロジー", "医薬品", "動物用医薬品"]


class PrTimesKeywordExtractor(Extractor):
    """Aggregate PR TIMES releases from keyword-tag listing pages.

    PR TIMES exposes no per-category RSS, but keyword topic pages
    (``/topics/keywords/<tag>``) are server-rendered and list recent
    releases with company, title, link and an ISO ``datetime``. One YAML
    row can therefore cover many issuers via ``config.keywords``.

    Each emitted release carries the *actual* posting company (parsed from
    the page), while ``crawl_mode`` is inherited from the source row so the
    aggregator can run in shadow independently of the per-issuer rows.
    """

    source_type = "prtimes"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        cfg = company.config
        keywords = cfg.get("keywords") or DEFAULT_KEYWORDS
        max_per_keyword = int(cfg.get("max_per_keyword", 10))
        results: list[RawRelease] = []
        seen: set[str] = set()

        for keyword in keywords:
            url = _KEYWORD_URL.format(keyword=quote(str(keyword)))
            try:
                html = self.http.get_text(url)
            except Exception:
                logger.info("PR TIMES: failed to fetch keyword page %s", keyword)
                continue
            for release in self._parse_keyword_page(html, max_per_keyword):
                if release.url in seen:
                    continue
                seen.add(release.url)
                results.append(release.model_copy(update={"crawl_mode": company.crawl_mode}))
                if len(results) >= limit:
                    return results
        return results

    def _parse_keyword_page(self, html: str, max_items: int) -> list[RawRelease]:
        soup = BeautifulSoup(html, "lxml")
        releases: list[RawRelease] = []
        for item in soup.select("article.item")[:max_items]:
            anchor = item.select_one("h3.title-item a[href]") or item.select_one(
                'a[href*="/main/html/rd/p/"]'
            )
            if not anchor or not anchor.get("href"):
                continue
            title = normalize_whitespace(anchor.get_text(" ", strip=True))
            if not title:
                continue
            url = urljoin(PRTIMES_BASE, anchor["href"])

            published = None
            time_el = item.select_one("time[datetime]")
            if time_el:
                published = parse_date(str(time_el.get("datetime") or ""))
                if not published:
                    published = parse_date(time_el.get_text(" ", strip=True))

            company_el = item.select_one("a.name-company, .name-company")
            company_name = (
                normalize_whitespace(company_el.get_text(" ", strip=True))
                if company_el
                else ""
            )
            if not company_name:
                continue

            releases.append(
                RawRelease(
                    company=company_name,
                    title=title,
                    url=url,
                    published_on=published,
                    summary="",
                    source_type=self.source_type,
                )
            )
        return releases
