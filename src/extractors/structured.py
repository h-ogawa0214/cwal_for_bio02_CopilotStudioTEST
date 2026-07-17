from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ..models import Company, RawRelease
from ..textutil import normalize_whitespace, parse_date
from .base import Extractor


def _dig(data: Any, path: str) -> Any:
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class JsonApiExtractor(Extractor):
    """Fetch release lists from JSON endpoints (CMS APIs, announcement feeds)."""

    source_type = "json_api"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        cfg = company.config
        json_url = cfg.get("json_url") or company.list_url
        raw = self.http.get_text(json_url)
        data = json.loads(raw)
        items = _dig(data, str(cfg.get("items_path") or "item"))
        if items is None:
            items = data if isinstance(data, list) else []
        if not isinstance(items, list):
            raise ValueError(f"{company.name}: json items_path did not yield a list")

        base_url = str(cfg.get("base_url") or company.list_url)
        html_field = cfg.get("html_field")
        title_field = cfg.get("title_field")
        url_field = cfg.get("url_field")
        date_field = cfg.get("date_field")
        results: list[RawRelease] = []
        seen: set[str] = set()

        for entry in items:
            if not isinstance(entry, dict):
                continue
            title = ""
            url = ""
            published = None
            summary = ""

            if html_field and entry.get(html_field):
                soup = BeautifulSoup(str(entry[html_field]), "lxml")
                link = soup.select_one(cfg.get("html_link_selector", "a"))
                if link and link.get("href"):
                    title = normalize_whitespace(link.get_text(" ", strip=True))
                    url = urljoin(base_url, link["href"])
                if not published and cfg.get("html_date_selector"):
                    date_el = soup.select_one(cfg["html_date_selector"])
                    if date_el:
                        published = parse_date(date_el.get_text(" ", strip=True))

            if title_field and not title:
                title = normalize_whitespace(str(entry.get(title_field) or ""))
            if url_field and not url:
                url = urljoin(base_url, str(entry.get(url_field) or "").strip())
            if date_field and not published:
                published = parse_date(entry.get(date_field))

            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append(
                RawRelease(
                    company=company.name,
                    title=title,
                    url=url,
                    published_on=published,
                    summary=summary,
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, url),
                )
            )
            if len(results) >= limit:
                break
        return results


class SitemapExtractor(Extractor):
    """Pull recent URLs from an XML sitemap (optionally filtered by regex)."""

    source_type = "sitemap"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        cfg = company.config
        sitemap_url = cfg.get("sitemap_url") or company.list_url
        xml_text = self.http.get_text(sitemap_url)
        root = ET.fromstring(xml_text)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"
        url_nodes = root.findall(f".//{ns}url")
        pattern = re.compile(str(cfg.get("url_regex") or ".*"))
        title_from_url = bool(cfg.get("title_from_url", True))
        results: list[RawRelease] = []
        for node in url_nodes:
            loc = (node.findtext(f"{ns}loc") or "").strip()
            if not loc or not pattern.search(loc):
                continue
            lastmod = parse_date(node.findtext(f"{ns}lastmod") or "")
            title = normalize_whitespace(loc.rsplit("/", 1)[-1].replace("-", " "))
            if not title_from_url:
                title = loc
            results.append(
                RawRelease(
                    company=company.name,
                    title=title or loc,
                    url=loc,
                    published_on=lastmod,
                    source_type=self.source_type,
                    reference_url=self.alternate_url(company, loc),
                )
            )
            if len(results) >= limit:
                break
        return results
