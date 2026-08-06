from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

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


@dataclass
class PendingReview:
    """A candidate that heuristics can't resolve alone; Claude Code judges it
    directly in the review-queue JSON (see src/main.py --dump-for-review /
    --apply-review). No LLM API call is made for this."""

    preselected_lead: str
    source_text: str
    heuristic_hint: str  # "keep" | "discard" | "uncertain"
    heuristic_reason: str
    original_title: str
    relevant_examples: list[dict] = field(default_factory=list)


@dataclass
class EvalResult:
    # Exactly one of the two is set.
    decision: dict | None = None
    pending: PendingReview | None = None


class Curator:
    def __init__(self, settings: Settings, metrics: RunMetrics | None = None) -> None:
        self.settings = settings
        self.criteria = _load_criteria()
        self.editorial_examples = _load_editorial_examples()
        self.metrics = metrics or RunMetrics()

    def evaluate(
        self,
        release: RawRelease,
        paragraph: str,
        source_text: str = "",
    ) -> EvalResult:
        """Cheap, deterministic pass only. Anything heuristics can't
        confidently discard is queued for Claude Code's review instead of
        being decided here."""
        paragraph = first_paragraph(paragraph or release.summary or release.title)
        title = normalize_whitespace(release.title)

        if _is_hard_discard_title(title):
            self.metrics.hard_discards += 1
            return EvalResult(
                decision={
                    "decision": "hard_discard",
                    "reason": "hard_title",
                    "model": "heuristic",
                    "criteria_version": self.settings.criteria_version,
                }
            )

        keep, reason = heuristic_decision(title, paragraph)

        if keep is False and not any(
            marker in f"{title} {paragraph}" for marker in KEY_PERSONNEL_MARKERS
        ):
            # Cheap path: unambiguous title discards skip review entirely.
            if any(kw in title for kw in DISCARD_KEYWORDS):
                self.metrics.heuristic_discards += 1
                return EvalResult(
                    decision={
                        "decision": "discard",
                        "reason": reason,
                        "model": "heuristic",
                        "criteria_version": self.settings.criteria_version,
                    }
                )

        # Everything else (heuristic keep still needing title/lead polish,
        # heuristic discard that wasn't an unambiguous keyword hit, and
        # heuristic "undecided") goes to Claude Code for judgment.
        self.metrics.pending_review += 1
        hint = "keep" if keep is True else ("discard" if keep is False else "uncertain")
        examples = _prompt_examples(_select_examples(self.editorial_examples, title, paragraph))
        return EvalResult(
            pending=PendingReview(
                preselected_lead=paragraph,
                source_text=compact_source_text(source_text, paragraph),
                heuristic_hint=hint,
                heuristic_reason=reason,
                original_title=title,
                relevant_examples=examples,
            )
        )

    def finalize_reviewed(
        self,
        release: RawRelease,
        pending: PendingReview,
        review: dict,
        *,
        reference_url: str = "",
    ) -> tuple[CuratedRelease | None, dict]:
        """Apply Claude Code's judgment (review: keep/reason/title/lead) to
        build the same output shape the old LLM-backed path produced."""
        published_on = release.published_on or date.today()
        title = pending.original_title
        keep = bool(review.get("keep"))
        reason = str(review.get("reason") or "").strip() or "claude_code_review"
        decision = {
            "reason": reason,
            "model": "claude-code",
            "stage": "review",
            "criteria_version": self.settings.criteria_version,
        }

        if not keep:
            self.metrics.discarded += 1
            decision["decision"] = "discard"
            return None, decision

        final_title = normalize_whitespace(str(review.get("title") or title)) or title
        edited_lead = normalize_whitespace(str(review.get("lead") or ""))
        paragraph = edited_lead if len(edited_lead) >= 40 else pending.preselected_lead
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
        decision["decision"] = "keep"
        return item, decision

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
