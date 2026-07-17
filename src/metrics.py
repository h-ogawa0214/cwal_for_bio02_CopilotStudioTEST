from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# Approximate gpt-4o-mini list prices (USD per 1M tokens).
_INPUT_PER_M = 0.15
_OUTPUT_PER_M = 0.60


@dataclass
class RunMetrics:
    candidates_seen: int = 0
    candidates_new: int = 0
    cache_hits: int = 0
    hard_discards: int = 0
    heuristic_discards: int = 0
    classify_calls: int = 0
    editorial_calls: int = 0
    kept: int = 0
    discarded: int = 0
    duplicates_skipped: int = 0
    fetch_errors: int = 0
    site_only: int = 0
    tdnet_only: int = 0
    matched_site_tdnet: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    source_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def record_source(self, source_type: str, *, fetched: int = 0, errors: int = 0) -> None:
        bucket = self.source_stats.setdefault(
            source_type or "unknown",
            {"fetched": 0, "errors": 0},
        )
        bucket["fetched"] += fetched
        bucket["errors"] += errors

    def add_usage(self, usage: object | None) -> None:
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    @property
    def llm_calls(self) -> int:
        return self.classify_calls + self.editorial_calls

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.prompt_tokens * _INPUT_PER_M
            + self.completion_tokens * _OUTPUT_PER_M
        ) / 1_000_000

    def summary_lines(self) -> list[str]:
        return [
            (
                f"metrics candidates={self.candidates_seen} new={self.candidates_new} "
                f"cache_hits={self.cache_hits} kept={self.kept} discarded={self.discarded}"
            ),
            (
                f"metrics llm_calls={self.llm_calls} "
                f"(classify={self.classify_calls}, editorial={self.editorial_calls}) "
                f"tokens_in={self.prompt_tokens} tokens_out={self.completion_tokens} "
                f"est_usd={self.estimated_cost_usd:.4f}"
            ),
            (
                f"metrics hard_discards={self.hard_discards} "
                f"heuristic_discards={self.heuristic_discards} "
                f"duplicates={self.duplicates_skipped} fetch_errors={self.fetch_errors}"
            ),
            (
                f"metrics site_only={self.site_only} tdnet_only={self.tdnet_only} "
                f"matched={self.matched_site_tdnet}"
            ),
        ]
