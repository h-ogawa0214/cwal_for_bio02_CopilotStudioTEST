from __future__ import annotations

from ..models import Company, RawRelease
from ..http_client import HttpClient


class Extractor:
    source_type: str = "base"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch(self, company: Company, limit: int) -> list[RawRelease]:
        raise NotImplementedError
