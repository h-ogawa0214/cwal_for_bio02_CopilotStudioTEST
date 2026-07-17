from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import RawRelease
from .textutil import first_paragraph, normalize_whitespace


def extract_body_paragraph(release: RawRelease, http: HttpClient) -> str:
    if release.summary:
        return first_paragraph(release.summary)

    url = release.url
    path = urlparse(url).path.lower()
    try:
        if path.endswith(".pdf"):
            data = http.get_bytes(url)
            reader = PdfReader(BytesIO(data))
            texts = []
            for page in reader.pages[:2]:
                texts.append(page.extract_text() or "")
            return first_paragraph("\n".join(texts))

        html = http.get_text(url)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        candidates = []
        for selector in [
            "article",
            "main",
            ".wd_content",
            ".news-detail",
            ".entry-content",
            "#content",
            ".content",
        ]:
            node = soup.select_one(selector)
            if node:
                candidates.append(normalize_whitespace(node.get_text(" ", strip=True)))
        if not candidates:
            candidates.append(normalize_whitespace(soup.get_text(" ", strip=True)))

        text = max(candidates, key=len)
        # Drop very short chrome
        text = re.sub(r"^.*?お知らせ", "お知らせ", text, count=1) if len(text) > 80 else text
        return first_paragraph(text)
    except Exception:
        return first_paragraph(release.title)
