from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    excel_file_path: str
    lookback_days: int
    tdnet_lookback_days: int
    max_items_per_company: int
    request_timeout_seconds: float
    user_agent: str
    companies_sheet: str = "companies"
    releases_sheet: str = "releases"
    decisions_sheet: str = "decisions"
    metrics_sheet: str = "metrics"
    dry_run: bool = False
    shadow_default: bool = False
    criteria_version: str = "eco-v1"


def _criteria_version() -> str:
    parts: list[bytes] = []
    for relative in ("config/criteria.md", "config/editorial_examples.json"):
        path = ROOT / relative
        if path.exists():
            parts.append(path.read_bytes())
    digest = hashlib.sha256(b"|".join(parts)).hexdigest()[:12]
    return f"eco-{digest}"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    excel_file_path = os.getenv(
        "EXCEL_FILE_PATH",
        str(ROOT / "data" / "releases.xlsx"),
    ).strip()

    return Settings(
        excel_file_path=excel_file_path,
        lookback_days=int(os.getenv("LOOKBACK_DAYS", "14")),
        tdnet_lookback_days=int(os.getenv("TDNET_LOOKBACK_DAYS", "3")),
        max_items_per_company=int(os.getenv("MAX_ITEMS_PER_COMPANY", "30")),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
        user_agent=os.getenv(
            "USER_AGENT",
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        ),
        dry_run=os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"},
        shadow_default=os.getenv("SHADOW_DEFAULT", "").lower() in {"1", "true", "yes"},
        criteria_version=_criteria_version(),
    )
