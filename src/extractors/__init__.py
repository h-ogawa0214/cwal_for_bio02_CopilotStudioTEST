from __future__ import annotations

from ..http_client import HttpClient
from ..models import Company, RawRelease
from .base import Extractor
from .eir import EirExtractor
from .feeds import RssExtractor, XlsxExtractor
from .html_css import HtmlCssExtractor, PlaywrightExtractor
from .noop import TdnetOnlyExtractor
from .structured import JsonApiExtractor, SitemapExtractor
from .tdnet import TdnetExtractor, fetch_tdnet_releases

__all__ = [
    "Extractor",
    "TdnetExtractor",
    "TdnetOnlyExtractor",
    "fetch_company_releases",
    "fetch_tdnet_releases",
    "get_extractor",
]


def get_extractor(source_type: str, http: HttpClient) -> Extractor:
    mapping: dict[str, type[Extractor]] = {
        HtmlCssExtractor.source_type: HtmlCssExtractor,
        PlaywrightExtractor.source_type: PlaywrightExtractor,
        RssExtractor.source_type: RssExtractor,
        XlsxExtractor.source_type: XlsxExtractor,
        TdnetExtractor.source_type: TdnetExtractor,
        TdnetOnlyExtractor.source_type: TdnetOnlyExtractor,
        JsonApiExtractor.source_type: JsonApiExtractor,
        SitemapExtractor.source_type: SitemapExtractor,
        EirExtractor.source_type: EirExtractor,
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
