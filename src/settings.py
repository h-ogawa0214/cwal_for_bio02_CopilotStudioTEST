from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    spreadsheet_id: str
    google_service_account_json: str
    openai_api_key: str
    openai_model: str
    lookback_days: int
    tdnet_lookback_days: int
    max_items_per_company: int
    request_timeout_seconds: float
    user_agent: str
    companies_sheet: str = "companies"
    releases_sheet: str = "releases"
    dry_run: bool = False


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if not sa_json and sa_file:
        sa_json = Path(sa_file).read_text(encoding="utf-8")
    if sa_json and not sa_json.startswith("{"):
        # Allow base64-ish mistakes to fail loudly later; prefer file path if given as plain path
        maybe_path = Path(sa_json)
        if maybe_path.exists():
            sa_json = maybe_path.read_text(encoding="utf-8")

    spreadsheet_id = os.getenv(
        "SPREADSHEET_ID",
        "1JlnCTJgC3ZdJ5WrHL9O6yPJsUE8uoVMEdGNSC8xb_6Y",
    ).strip()

    return Settings(
        spreadsheet_id=spreadsheet_id,
        google_service_account_json=sa_json,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=(os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
        or "gpt-4o-mini",
        lookback_days=int(os.getenv("LOOKBACK_DAYS", "14")),
        # TDnet viewing service keeps ~31 days; keep crawl light for 3x/day runs.
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
    )


def validate_service_account_json(raw: str) -> dict:
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON (or GOOGLE_SERVICE_ACCOUNT_FILE) is required"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    if data.get("type") != "service_account":
        raise RuntimeError("Credentials JSON must be a Google service account key")
    return data
