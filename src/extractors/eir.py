from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Company, RawRelease
from ..textutil import normalize_whitespace, parse_date
from .base import Extractor
from .html_css import PlaywrightExtractor


_EIR_JS_CANDIDATES = [
    "https://ssl4.eir-parts.net/doc/{code}/tdnet/tdnet_1.js",
    "https://ssl4.eir-parts.net/doc/{code}/tdnet/ja/tdnet_1.js",
    "https://ssl4.eir-parts.net/doc/{code}/announcement/announcement_1.js",
    "https://ssl4.eir-parts.net/doc/{code}/announcement1/ja/announcement_1.js",
    "https://ssl.eir-parts.net/doc/{code}/tdnet/tdnet_1.js",
]


class EirExtractor(Extractor):
    """Shared adapter for Pronexus/EIR-powered IR news widgets.

    Tries lightweight JS data endpoints first, then falls back to Playwright
    against the company list page (`.eir a`).
    """

    source_type = "eir"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        code = (company.stock_code or company.config.get("eir_code") or "").strip()
        if code:
            for template in company.config.get("eir_js_urls") or _EIR_JS_CANDIDATES:
                url = str(template).format(code=code)
                try:
                    text = self.http.get_text(url)
                except Exception:
                    continue
                parsed = self._parse_eir_js(company, text, limit=limit)
                if parsed:
                    return parsed

        # Fallback: render the IR page and scrape the EIR widget links.
        playwright_company = company.model_copy(
            update={
                "source_type": "playwright",
                "config": {
                    **company.config,
                    "wait_selector": company.config.get(
                        "wait_selector",
                        ".eir a, .eir_list a, a[href*='pdf'], a[href*='news']",
                    ),
                    "link_selector": company.config.get("link_selector", ".eir a"),
                    "min_title_length": company.config.get("min_title_length", 12),
                    "same_host_only": company.config.get("same_host_only", False),
                },
            }
        )
        items = PlaywrightExtractor(self.http).fetch(playwright_company, limit=limit)
        return [
            item.model_copy(update={"source_type": self.source_type}) for item in items
        ]

    def _parse_eir_js(
        self, company: Company, text: str, *, limit: int
    ) -> list[RawRelease]:
        # EIR payloads often embed HTML fragments or pipe-delimited records.
        results: list[RawRelease] = []
        seen: set[str] = set()
        base = company.list_url
        for match in re.finditer(
            r"href=[\"']([^\"']+)[\"'][^>]*>([^<]{8,200})", text, flags=re.I
        ):
            href, title = match.group(1), normalize_whitespace(match.group(2))
            url = urljoin(base, href)
            if url in seen or len(title) < 8:
                continue
            seen.add(url)
            nearby = text[max(0, match.start() - 120) : match.end() + 40]
            published = parse_date(nearby)
            results.append(
                RawRelease(
                    company=company.name,
                    title=title,
                    url=url,
                    published_on=published,
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, url),
                )
            )
            if len(results) >= limit:
                break
        if results:
            return results

        soup = BeautifulSoup(text, "lxml")
        for a in soup.select("a[href]"):
            title = normalize_whitespace(a.get_text(" ", strip=True))
            href = a.get("href") or ""
            if not href or len(title) < 8:
                continue
            url = urljoin(base, href)
            if url in seen:
                continue
            seen.add(url)
            results.append(
                RawRelease(
                    company=company.name,
                    title=title,
                    url=url,
                    published_on=parse_date(a.parent.get_text(" ", strip=True) if a.parent else ""),
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, url),
                )
            )
            if len(results) >= limit:
                break
        return results
