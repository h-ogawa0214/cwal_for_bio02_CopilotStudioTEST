from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class RunMetrics:
    candidates_seen: int = 0
    candidates_new: int = 0
    cache_hits: int = 0
    hard_discards: int = 0
    heuristic_discards: int = 0
    pending_review: int = 0
    kept: int = 0
    discarded: int = 0
    duplicates_skipped: int = 0
    fetch_errors: int = 0
    site_only: int = 0
    tdnet_only: int = 0
    matched_site_tdnet: int = 0
    source_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def record_source(self, source_type: str, *, fetched: int = 0, errors: int = 0) -> None:
        bucket = self.source_stats.setdefault(
            source_type or "unknown",
            {"fetched": 0, "errors": 0},
        )
        bucket["fetched"] += fetched
        bucket["errors"] += errors

    def to_dict(self) -> dict:
        """Serialize for the dump→review→apply hand-off (see src/main.py)."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RunMetrics":
        payload = dict(data)
        started_at_raw = payload.pop("started_at", None)
        metrics = cls(**payload)
        if started_at_raw:
            metrics.started_at = datetime.fromisoformat(started_at_raw)
        return metrics

    def summary_lines(self) -> list[str]:
        return [
            (
                f"metrics candidates={self.candidates_seen} new={self.candidates_new} "
                f"cache_hits={self.cache_hits} kept={self.kept} discarded={self.discarded} "
                f"pending_review={self.pending_review}"
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
