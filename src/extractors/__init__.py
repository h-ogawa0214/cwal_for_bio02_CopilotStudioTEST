from __future__ import annotations

from ..http_client import HttpClient
from ..models import Company, RawRelease
from .base import Extractor
from .feeds import RssExtractor, XlsxExtractor
from .html_css import HtmlCssExtractor, PlaywrightExtractor


def get_extractor(source_type: str, http: HttpClient) -> Extractor:
    mapping: dict[str, type[Extractor]] = {
        HtmlCssExtractor.source_type: HtmlCssExtractor,
        PlaywrightExtractor.source_type: PlaywrightExtractor,
        RssExtractor.source_type: RssExtractor,
        XlsxExtractor.source_type: XlsxExtractor,
    }
    cls = mapping.get(source_type)
    if not cls:
        raise ValueError(f"Unsupported source_type: {source_type}")
    return cls(http)


def fetch_company_releases(
    company: Company, http: HttpClient, limit: int
) -> list[RawRelease]:
    extractor = get_extractor(company.source_type, http)
    return extractor.fetch(company, limit=limit)
