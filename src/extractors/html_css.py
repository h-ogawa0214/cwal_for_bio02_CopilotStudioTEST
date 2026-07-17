from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Company, RawRelease
from ..textutil import normalize_whitespace, parse_date
from .base import Extractor


class HtmlCssExtractor(Extractor):
    source_type = "html_css"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        cfg = company.config
        html = self.http.get_text(company.list_url)
        soup = BeautifulSoup(html, "lxml")
        items = soup.select(cfg.get("item_selector", "li"))
        results: list[RawRelease] = []
        seen: set[str] = set()

        for item in items:
            title_el = item.select_one(cfg.get("title_selector", "a"))
            link_el = item.select_one(cfg.get("link_selector", "a"))
            if not title_el or not link_el or not link_el.get("href"):
                continue
            title = normalize_whitespace(title_el.get_text(" ", strip=True))
            if len(title) < int(cfg.get("min_title_length", 8)):
                continue
            url = urljoin(company.list_url, link_el["href"])
            if url in seen:
                continue
            seen.add(url)

            date_text = ""
            if cfg.get("date_selector"):
                date_el = item.select_one(cfg["date_selector"])
                if date_el:
                    date_text = date_el.get_text(" ", strip=True)
            if not date_text:
                date_text = item.get_text(" ", strip=True)

            summary = ""
            if cfg.get("summary_selector"):
                summary_el = item.select_one(cfg["summary_selector"])
                if summary_el:
                    summary = normalize_whitespace(summary_el.get_text(" ", strip=True))

            results.append(
                RawRelease(
                    company=company.name,
                    title=title,
                    url=url,
                    published_on=parse_date(date_text),
                    summary=summary,
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, url),
                )
            )
            if len(results) >= limit:
                break
        return results


class PlaywrightExtractor(Extractor):
    source_type = "playwright"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        from playwright.sync_api import sync_playwright

        cfg = company.config
        wait_selector = cfg.get("wait_selector", "a")
        link_selector = cfg.get("link_selector", "a")
        min_title_length = int(cfg.get("min_title_length", 12))
        same_host_only = bool(cfg.get("same_host_only", False))
        host = urlparse(company.list_url).netloc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.http._client.headers["User-Agent"])
            page.goto(company.list_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector(wait_selector, timeout=25000)
            except Exception:
                # Some sites hydrate slowly; continue with whatever is present.
                page.wait_for_timeout(3000)
            # Extra settle time for EIR widgets
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        results: list[RawRelease] = []
        seen: set[str] = set()
        for a in soup.select(link_selector):
            href = a.get("href")
            title = normalize_whitespace(a.get_text(" ", strip=True))
            if not href or len(title) < min_title_length:
                continue
            if title.startswith("もっと詳しく"):
                continue
            url = urljoin(company.list_url, href)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if same_host_only and parsed.netloc and parsed.netloc != host:
                continue
            if url in seen:
                continue
            seen.add(url)

            # Try to find a nearby date in parent blocks
            date_text = ""
            parent = a.parent
            for _ in range(4):
                if parent is None:
                    break
                date_text = parent.get_text(" ", strip=True)
                if parse_date(date_text):
                    break
                parent = parent.parent

            results.append(
                RawRelease(
                    company=company.name,
                    title=title,
                    url=url,
                    published_on=parse_date(date_text),
                    summary="",
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, url),
                )
            )
            if len(results) >= limit:
                break
        return results
