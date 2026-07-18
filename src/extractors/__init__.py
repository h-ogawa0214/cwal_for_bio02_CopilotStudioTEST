from __future__ import annotations

from ..http_client import HttpClient
from ..models import Company, RawRelease
from .base import Extractor
from .eir import EirExtractor
from .feeds import RssExtractor, XlsxExtractor
from .html_css import HtmlCssExtractor, PlaywrightExtractor
from .noop import TdnetOnlyExtractor
from .prtimes import PrTimesCompanyExtractor, PrTimesKeywordExtractor
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
        PrTimesKeywordExtractor.source_type: PrTimesKeywordExtractor,
        PrTimesCompanyExtractor.source_type: PrTimesCompanyExtractor,
    }
    cls = mapping.get(source_type)
    if not cls:
        raise ValueError(f"Unsupported source_type: {source_type}")
    return cls(http)


def fetch_company_releases(
    company: Company, http: HttpClient, limit: int
) -> list[RawRelease]:
    extractor = get_extractor(company.source_type, http)
    releases = extractor.fetch(company, limit=limit)
    # Stamp the owning row's crawl_mode unless the extractor set it per-release
    # (aggregators like PR TIMES emit many issuers under one shadow row).
    return [
        release if release.crawl_mode != "live" else release.model_copy(
            update={"crawl_mode": company.crawl_mode}
        )
        for release in releases
    ]
