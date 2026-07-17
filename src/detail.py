from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import RawRelease
from .textutil import first_paragraph, normalize_whitespace, parse_date


@dataclass(frozen=True)
class ExtractedDetail:
    paragraph: str
    published_on: date | None = None
    reference_url: str = ""


def extract_release_detail(release: RawRelease, http: HttpClient) -> ExtractedDetail:
    url = release.url
    path = urlparse(url).path.lower()
    try:
        if path.endswith(".pdf"):
            data = http.get_bytes(url)
            reader = PdfReader(BytesIO(data))
            texts = []
            for page in reader.pages[:2]:
                texts.append(page.extract_text() or "")
            text = "\n".join(texts)
            return ExtractedDetail(
                paragraph=_select_substantive_paragraph(text)
                or first_paragraph(release.summary)
                or release.title,
                published_on=parse_date(text[:1500]),
            )

        html = http.get_text(url)
        soup = BeautifulSoup(html, "lxml")
        published_on = _extract_html_date(soup)
        containers = []
        for selector in [
            ".wd_body.wd_news_body",
            ".wd_body",
            "article",
            "main",
            ".news-detail",
            ".entry-content",
            "#content",
            ".content",
        ]:
            node = soup.select_one(selector)
            if node and node not in containers:
                containers.append(node)

        for container in containers:
            paragraphs = [
                normalize_whitespace(p.get_text(" ", strip=True))
                for p in container.select("p")
            ]
            paragraph = _select_substantive_paragraphs(paragraphs)
            if paragraph:
                return ExtractedDetail(paragraph=paragraph, published_on=published_on)

        body_text = normalize_whitespace(soup.get_text(" ", strip=True))
        return ExtractedDetail(
            paragraph=_select_substantive_paragraph(body_text)
            or first_paragraph(release.summary)
            or release.title,
            published_on=published_on,
        )
    except Exception:
        if release.reference_url and release.reference_url != release.url:
            alternate = release.model_copy(
                update={"url": release.reference_url, "reference_url": ""}
            )
            detail = extract_release_detail(alternate, http)
            return ExtractedDetail(
                paragraph=detail.paragraph,
                published_on=detail.published_on,
                reference_url=release.reference_url,
            )
        return ExtractedDetail(
            paragraph=first_paragraph(release.summary) or release.title,
        )


def _extract_html_date(soup: BeautifulSoup) -> date | None:
    for selector, attribute in [
        ('meta[property="article:published_time"]', "content"),
        ('meta[name="date"]', "content"),
        ('meta[name="publish-date"]', "content"),
        ("time[datetime]", "datetime"),
    ]:
        node = soup.select_one(selector)
        if node:
            parsed = parse_date(str(node.get(attribute) or ""))
            if parsed:
                return parsed
    for selector in [".wd_date", ".date", ".published", "time"]:
        node = soup.select_one(selector)
        if node:
            parsed = parse_date(node.get_text(" ", strip=True))
            if parsed:
                return parsed
    return None


def _select_substantive_paragraph(text: str) -> str:
    blocks = [
        normalize_whitespace(block)
        for block in re.split(r"(?:\r?\n\s*){2,}", text)
        if normalize_whitespace(block)
    ]
    return _select_substantive_paragraphs(blocks)


def _select_substantive_paragraphs(paragraphs: list[str]) -> str:
    for paragraph in paragraphs:
        if _is_substantive_paragraph(paragraph):
            return first_paragraph(paragraph)
    return ""


def _is_substantive_paragraph(text: str) -> bool:
    if len(text) < 80:
        return False
    if text.startswith(("-", "‐", "－", "※", "注：", "注意事項")):
        return False
    boilerplate = (
        "本ニュースリリース",
        "このニュースリリース",
        "将来の見通し",
        "報道関係者",
        "お問い合わせ",
    )
    if any(text.startswith(prefix) for prefix in boilerplate):
        return False
    company_intro = (
        "Inc.（本社",
        "大学",
        "研究所",
        "共同で",
        "締結した",
    )
    return bool(re.search(r"株式会社\s*[（(]本社", text)) or any(
        marker in text for marker in company_intro
    )


# Backward-compatible wrapper for callers/tests outside the package.
def extract_body_paragraph(release: RawRelease, http: HttpClient) -> str:
    return extract_release_detail(release, http).paragraph
