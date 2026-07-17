from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from openai import OpenAI

from .metrics import RunMetrics
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

KEY_PERSONNEL_MARKERS = (
    "代表取締役",
    "社長",
    "CEO",
    "CFO",
    "CSO",
    "EVP",
    "エグゼクティブ",
    "経営体制",
)


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


def _select_examples(examples: list[dict], title: str, paragraph: str) -> list[dict]:
    text = f"{title} {paragraph}"
    scored: list[tuple[int, dict]] = []
    for example in examples:
        score = 0
        note = str(example.get("note") or "")
        source_title = str(example.get("source_title") or "")
        if any(marker in text for marker in KEY_PERSONNEL_MARKERS) and (
            "キーパーソン" in note or "EVP" in source_title or "エクゼクティブ" in source_title
        ):
            score += 3
        if ("親会社" in note or "子会社" in note) and (
            "子会社" in text or "ホールディングス" in text or "親会社" in note
        ):
            score += 3
        if ("など" in note or "多数" in note) and ("および" in text or "共同" in text):
            score += 2
        if ("主語" in note or "補" in note) and len(title) < 24:
            score += 2
        if "PDF" in note and ".pdf" in text.lower():
            score += 1
        if score == 0:
            score = 1  # keep general examples eligible
        scored.append((score, example))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [example for _, example in scored[:4]]
    return selected or examples[:3]


def heuristic_decision(title: str, paragraph: str) -> tuple[bool | None, str]:
    """Title-focused heuristic. Keep signals beat discard unless title-only noise."""
    title_text = title or ""
    body = paragraph or ""
    combined = f"{title_text} {body}"

    if _is_hard_discard_title(title_text):
        return False, "heuristic discard:hard_title"

    keep_hits = [kw for kw in KEEP_KEYWORDS if kw in combined]
    if keep_hits:
        return True, f"heuristic keep:{','.join(keep_hits[:3])}"

    # Key personnel exception to generic HR discards.
    if any(marker in combined for marker in KEY_PERSONNEL_MARKERS):
        return True, "heuristic keep:key_personnel"

    for kw in DISCARD_KEYWORDS:
        if kw in title_text:
            return False, f"heuristic discard:{kw}"
    return None, "heuristic undecided"


def _is_hard_discard_title(title: str) -> bool:
    normalized = normalize_whitespace(title)
    return any(pattern.search(normalized) for pattern in HARD_DISCARD_TITLE_PATTERNS)


def compact_source_text(source_text: str, paragraph: str, *, max_chars: int = 3500) -> str:
    blocks = [
        normalize_whitespace(block)
        for block in re.split(r"(?:\r?\n\s*){2,}", source_text or "")
        if normalize_whitespace(block)
    ]
    if not blocks:
        return (paragraph or "")[:max_chars]
    selected: list[str] = []
    if paragraph:
        selected.append(normalize_whitespace(paragraph))
    for block in blocks:
        if paragraph and normalize_whitespace(paragraph) in block:
            continue
        if len(block) < 40:
            continue
        selected.append(block)
        if len(selected) >= 5:
            break
    text = "\n\n".join(selected)
    return text[:max_chars]


class Curator:
    def __init__(self, settings: Settings, metrics: RunMetrics | None = None) -> None:
        self.settings = settings
        self.criteria = _load_criteria()
        self.editorial_examples = _load_editorial_examples()
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.metrics = metrics or RunMetrics()

    def curate(
        self,
        release: RawRelease,
        paragraph: str,
        reference_url: str = "",
        source_text: str = "",
    ) -> CuratedRelease | None:
        result, _decision = self.curate_with_decision(
            release,
            paragraph,
            reference_url=reference_url,
            source_text=source_text,
        )
        return result

    def curate_with_decision(
        self,
        release: RawRelease,
        paragraph: str,
        reference_url: str = "",
        source_text: str = "",
    ) -> tuple[CuratedRelease | None, dict]:
        published_on = release.published_on or date.today()
        paragraph = first_paragraph(paragraph or release.summary or release.title)
        title = normalize_whitespace(release.title)
        decision = {
            "decision": "discard",
            "reason": "",
            "model": self.settings.openai_model if self.client else "heuristic",
            "criteria_version": self.settings.criteria_version,
        }

        if _is_hard_discard_title(title):
            self.metrics.hard_discards += 1
            decision.update({"decision": "hard_discard", "reason": "hard_title"})
            return None, decision

        keep, reason = heuristic_decision(title, paragraph)
        final_title = title
        stage = "heuristic"

        if keep is False and not any(marker in f"{title} {paragraph}" for marker in KEY_PERSONNEL_MARKERS):
            # Cheap path: unambiguous title discards skip LLM entirely.
            if any(kw in title for kw in DISCARD_KEYWORDS):
                self.metrics.heuristic_discards += 1
                decision.update({"decision": "discard", "reason": reason})
                return None, decision

        needs_editorial = keep is True
        if self.client:
            if keep is not True:
                classification = self._llm_classify(title, paragraph, release.company)
                stage = "classify"
                verdict = str(classification.get("verdict") or "uncertain").lower()
                reason = str(classification.get("reason") or reason)
                if verdict == "discard":
                    self.metrics.discarded += 1
                    decision.update(
                        {"decision": "discard", "reason": reason, "stage": stage}
                    )
                    return None, decision
                needs_editorial = verdict in {"keep", "uncertain"}
                keep = verdict == "keep"
            if needs_editorial:
                editorial = self._llm_edit(
                    title,
                    paragraph,
                    release.company,
                    source_text=source_text,
                )
                stage = "editorial"
                keep = bool(editorial.get("keep", keep if keep is not None else False))
                reason = str(editorial.get("reason") or reason)
                final_title = (
                    normalize_whitespace(str(editorial.get("title") or title)) or title
                )
                edited_lead = normalize_whitespace(str(editorial.get("lead") or ""))
                if len(edited_lead) >= 40:
                    paragraph = edited_lead
        elif keep is None:
            decision.update({"decision": "discard", "reason": "heuristic_undecided"})
            return None, decision

        if not keep:
            self.metrics.discarded += 1
            decision.update({"decision": "discard", "reason": reason, "stage": stage})
            return None, decision

        if len(final_title) < 8:
            final_title = self._fallback_title(title, paragraph)

        self.metrics.kept += 1
        item = CuratedRelease(
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
            source_type=release.source_type,
        )
        decision.update({"decision": "keep", "reason": reason, "stage": stage})
        return item, decision

    def _llm_classify(self, title: str, paragraph: str, company: str) -> dict:
        prompt = {
            "company": company,
            "source_title": title,
            "preselected_lead": paragraph[:1200],
            "instructions": (
                "掲載可否だけを判定してください。"
                "verdictは keep / discard / uncertain のいずれか。"
                "明らかにIR定型・採用・説明会・自己株式などは discard。"
                "治験・承認・提携・上市・重要経営人事は keep。"
                "迷う場合のみ uncertain。"
            ),
            "criteria_summary": self.criteria[:1800],
        }
        response = self.client.chat.completions.create(
            model=self.settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a triage editor for a Japanese biotech magazine. "
                        "Return JSON with keys: verdict (keep|discard|uncertain), reason (string)."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        self.metrics.classify_calls += 1
        self.metrics.add_usage(getattr(response, "usage", None))
        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"verdict": "uncertain", "reason": "llm_parse_error"}
        if str(data.get("verdict") or "").lower() not in {"keep", "discard", "uncertain"}:
            data["verdict"] = "uncertain"
        return data

    def _llm_edit(
        self,
        title: str,
        paragraph: str,
        company: str,
        *,
        source_text: str = "",
    ) -> dict:
        examples = _select_examples(self.editorial_examples, title, paragraph)
        prompt = {
            "company": company,
            "source_title": title,
            "preselected_lead": paragraph,
            "source_text": compact_source_text(source_text, paragraph),
            "instructions": (
                "お手本と同じ編集方針で掲載タイトルとリードを作ってください。"
                "keep=true/false、reasonは短く。"
                "titleは発表主体を必要に応じて補い、多数主体は中心機関＋「など」に縮約。"
                "親子会社が重要なら上場親会社も補う。"
                "leadは原文の事実を変えず、明白な抽出崩れだけ修正。"
            ),
            "criteria": self.criteria,
            "editorial_examples": _prompt_examples(examples),
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
        self.metrics.editorial_calls += 1
        self.metrics.add_usage(getattr(response, "usage", None))
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
    return normalized.endswith("お知らせ") and len(normalized) < 24
