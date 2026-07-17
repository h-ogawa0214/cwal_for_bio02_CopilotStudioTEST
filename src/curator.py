from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from openai import OpenAI

from .models import CuratedRelease, RawRelease
from .settings import ROOT, Settings
from .textutil import first_paragraph, normalize_whitespace


DISCARD_KEYWORDS = [
    "採用",
    "求人",
    "インターン",
    "セミナー",
    "説明会",
    "イベント開催",
    "キャンペーン",
    "啓発",
    "自己株式",
    "自己株",
    "選定のお知らせ",
    "銘柄に選定",
    "銘柄選定",
    "健康経営",
    "なでしこ銘柄",
    "DX銘柄",
    "ESG",
    "受賞",
    "表彰",
    "人事のお知らせ",
    "役員の異動",
    "組織改正",
    "お別れの会",
]

KEEP_KEYWORDS = [
    "承認",
    "申請",
    "適応追加",
    "臨床試験",
    "治験",
    "第I相",
    "第II相",
    "第III相",
    "第Ⅰ相",
    "第Ⅱ相",
    "第Ⅲ相",
    "第I/II相",
    "共同研究",
    "提携",
    "ライセンス",
    "資本業務提携",
    "業務提携",
    "共同販売",
    "契約締結",
    "資金調達",
    "出資",
    "増資",
    "発売",
    "上市",
    "新発売",
    "新製品",
    "製造販売",
    "研究成果",
    "論文",
    "検証的試験",
]


def _load_criteria() -> str:
    path = ROOT / "config" / "criteria.md"
    return path.read_text(encoding="utf-8")


def heuristic_decision(title: str, paragraph: str) -> tuple[bool | None, str]:
    text = f"{title} {paragraph}"
    for kw in DISCARD_KEYWORDS:
        if kw in text:
            return False, f"heuristic discard:{kw}"
    keep_hits = [kw for kw in KEEP_KEYWORDS if kw in text]
    if keep_hits:
        return True, f"heuristic keep:{','.join(keep_hits[:3])}"
    return None, "heuristic undecided"


class Curator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.criteria = _load_criteria()
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def curate(self, release: RawRelease, paragraph: str) -> CuratedRelease | None:
        published_on = release.published_on or date.today()
        paragraph = first_paragraph(paragraph or release.summary or release.title)
        title = normalize_whitespace(release.title)

        keep: bool | None
        reason: str
        final_title = title

        keep, reason = heuristic_decision(title, paragraph)
        if self.client:
            llm = self._llm_decide(title, paragraph, release.company)
            keep = bool(llm["keep"])
            reason = str(llm.get("reason") or reason)
            final_title = normalize_whitespace(str(llm.get("title") or title)) or title
        elif keep is None:
            # Without LLM, skip undecided items to avoid noisy sheet rows
            return None

        if not keep:
            return None

        if len(final_title) < 8:
            final_title = self._fallback_title(title, paragraph)

        return CuratedRelease(
            published_on=published_on,
            company=release.company,
            title=final_title,
            paragraph=paragraph,
            url=release.url,
            keep=True,
            reason=reason,
            original_title=title,
            fetched_at=datetime.now(timezone.utc),
        )

    def _llm_decide(self, title: str, paragraph: str, company: str) -> dict:
        prompt = {
            "company": company,
            "title": title,
            "paragraph": paragraph,
            "instructions": (
                "創薬・バイオ領域の雑誌サイト向けに、このリリースを掲載すべきか判定してください。"
                "keep=true/false、reasonは短く、titleは必要なら40字前後で補正。"
                "元タイトルが十分具体的なら尊重。"
            ),
            "criteria": self.criteria,
        }
        response = self.client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an editor for a Japanese biotech/pharma magazine website. "
                        "Return JSON with keys: keep (boolean), reason (string), title (string)."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"keep": False, "reason": "llm_parse_error", "title": title}
        if "keep" not in data:
            data["keep"] = False
        if "title" not in data or not str(data["title"]).strip():
            data["title"] = title
        return data

    @staticmethod
    def _fallback_title(title: str, paragraph: str) -> str:
        base = paragraph or title
        base = re.split(r"[。\.]", base)[0]
        base = normalize_whitespace(base)
        if len(base) > 42:
            return base[:41] + "…"
        return base or title
