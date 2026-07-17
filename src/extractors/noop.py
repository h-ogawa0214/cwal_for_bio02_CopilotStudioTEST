from __future__ import annotations

from ..models import Company, RawRelease
from .base import Extractor


class TdnetOnlyExtractor(Extractor):
    """Placeholder extractor: site crawl is skipped; TDnet aggregate covers the issuer."""

    source_type = "tdnet_only"

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        return []
