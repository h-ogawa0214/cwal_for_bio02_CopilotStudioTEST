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

HARD_DISCARD_TITLE_PATTERNS = [
    re.compile(r"助成金(?:の)?受領(?:に関する)?(?:お知らせ)?"),
    re.compile(r"よくあるご質問(?:と回答)?"),
    re.compile(r"説明会.*(?:質問|質疑)"),
    re.compile(r"(?:質問と回答|質疑応答|Q\s*&\s*A)", re.IGNORECASE),
    re.compile(r"払込完了(?:に関する)?(?:お知らせ)?"),
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


def _load_editorial_examples() -> list[dict]:
    path = ROOT / "config" / "editorial_examples.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _prompt_examples(examples: list[dict]) -> list[dict]:
    """Drop provenance-only fields to keep the per-item prompt compact."""
    return [
        {
            "source_title": example.get("source_title", ""),
            "source_excerpt": example.get("source_excerpt", ""),
            "output_title": example.get("output_title", ""),
            "output_lead": example.get("output_lead", ""),
            "editorial_note": example.get("note", ""),
        }
        for example in examples
    ]


def heuristic_decision(title: str, paragraph: str) -> tuple[bool | None, str]:
    text = f"{title} {paragraph}"
    for kw in DISCARD_KEYWORDS:
        if kw in text:
            return False, f"heuristic discard:{kw}"
    keep_hits = [kw for kw in KEEP_KEYWORDS if kw in text]
    if keep_hits:
        return True, f"heuristic keep:{','.join(keep_hits[:3])}"
    return None, "heuristic undecided"


def _is_hard_discard_title(title: str) -> bool:
    normalized = normalize_whitespace(title)
    return any(pattern.search(normalized) for pattern in HARD_DISCARD_TITLE_PATTERNS)


class Curator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.criteria = _load_criteria()
        self.editorial_examples = _load_editorial_examples()
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def curate(
        self,
        release: RawRelease,
        paragraph: str,
        reference_url: str = "",
        source_text: str = "",
    ) -> CuratedRelease | None:
        published_on = release.published_on or date.today()
        paragraph = first_paragraph(paragraph or release.summary or release.title)
        title = normalize_whitespace(release.title)
        if _is_hard_discard_title(title):
            return None

        keep: bool | None
        reason: str
        final_title = title

        keep, reason = heuristic_decision(title, paragraph)
        if self.client:
            llm = self._llm_decide(
                title,
                paragraph,
                release.company,
                source_text=source_text,
            )
            keep = bool(llm["keep"])
            reason = str(llm.get("reason") or reason)
            final_title = normalize_whitespace(str(llm.get("title") or title)) or title
            edited_lead = normalize_whitespace(str(llm.get("lead") or ""))
            if len(edited_lead) >= 40:
                paragraph = edited_lead
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
            reference_url=reference_url,
            fetched_at=datetime.now(timezone.utc),
        )

    def _llm_decide(
        self,
        title: str,
        paragraph: str,
        company: str,
        *,
        source_text: str = "",
    ) -> dict:
        prompt = {
            "company": company,
            "source_title": title,
            "preselected_lead": paragraph,
            "source_text": (source_text or paragraph)[:12000],
            "instructions": (
                "創薬・バイオ領域の雑誌サイト向けに掲載可否を判定し、"
                "お手本と同じ編集方針で掲載タイトルとリードを作ってください。"
                "titleは十分具体的な原題を尊重しつつ、必要な発表主体を補い、"
                "多数主体は中心機関＋「など」に縮約し、媒体ジャンル外の主体は省略可能です。"
                "親子会社関係が記事価値の理解に重要なら上場親会社も補ってください。"
                "leadはsource_textから最も適切な実質的段落を選び、原文の事実・数値・固有名詞を"
                "変えず、明白な抽出崩れだけ修正してください。推測や新情報を加えないでください。"
                "JSONでkeep、reason、title、leadを返してください。"
            ),
            "criteria": self.criteria,
            "editorial_examples": _prompt_examples(self.editorial_examples),
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
                        "Follow the supplied publication examples. Return JSON with keys: "
                        "keep (boolean), reason (string), title (string), lead (string)."
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
        if "lead" not in data or not str(data["lead"]).strip():
            data["lead"] = paragraph
        return data

    @staticmethod
    def _fallback_title(title: str, paragraph: str) -> str:
        base = paragraph or title
        base = re.split(r"[。\.]", base)[0]
        base = normalize_whitespace(base)
        if len(base) > 42:
            return base[:41] + "…"
        return base or title


def _is_vague_title(title: str) -> bool:
    normalized = normalize_whitespace(title)
    generic_titles = {
        "お知らせ",
        "ニュースリリース",
        "プレスリリース",
        "研究成果について",
        "共同研究について",
        "業務提携について",
        "承認取得について",
    }
    if normalized in generic_titles or len(normalized) < 15:
        return True
    # A concrete title normally contains a named subject and an action. Long,
    # descriptive originals must not be shortened merely for style.
    return normalized.endswith("お知らせ") and len(normalized) < 24
