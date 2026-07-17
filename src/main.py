from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from .companies import load_companies_from_yaml
from .curator import Curator
from .detail import extract_body_paragraph
from .extractors import fetch_company_releases
from .http_client import HttpClient
from .settings import load_settings
from .sheets_client import SheetsClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("pr-disclosure-curator")


def run(seed_only: bool = False) -> int:
    settings = load_settings()
    yaml_companies = load_companies_from_yaml()

    if not settings.google_service_account_json:
        logger.error("Google service account credentials are missing")
        return 2

    sheets = SheetsClient(settings)
    sheets.ensure_schema()
    seeded = sheets.seed_companies_if_empty(yaml_companies)
    if seeded:
        logger.info("Seeded %s companies into spreadsheet", seeded)

    if seed_only:
        return 0

    companies = [c for c in sheets.load_companies() if c.enabled]
    if not companies:
        # Fallback to local YAML if sheet unexpectedly empty after seed attempt
        companies = [c for c in yaml_companies if c.enabled]
        logger.warning("Using local YAML companies (%s)", len(companies))

    existing_urls = sheets.existing_urls()
    http = HttpClient(settings.user_agent, settings.request_timeout_seconds)
    curator = Curator(settings)
    cutoff = date.today() - timedelta(days=settings.lookback_days)

    curated = []
    errors = 0
    try:
        for company in companies:
            logger.info("Crawling %s (%s)", company.name, company.source_type)
            try:
                raw_items = fetch_company_releases(
                    company, http, limit=settings.max_items_per_company
                )
            except Exception:
                logger.exception("Failed to fetch %s", company.name)
                errors += 1
                continue

            for raw in raw_items:
                if raw.url in existing_urls:
                    continue
                if raw.published_on and raw.published_on < cutoff:
                    continue
                try:
                    paragraph = extract_body_paragraph(raw, http)
                    item = curator.curate(raw, paragraph)
                except Exception:
                    logger.exception("Failed to curate: %s", raw.url)
                    errors += 1
                    continue
                if item is None:
                    continue
                curated.append(item)
                existing_urls.add(item.url)
                logger.info("KEEP %s | %s", item.company, item.title)
    finally:
        http.close()

    curated.sort(key=lambda x: (x.published_on, x.company, x.title), reverse=True)

    if settings.dry_run:
        logger.info("DRY_RUN enabled; skipping spreadsheet write (%s items)", len(curated))
        for item in curated:
            print(
                f"{item.published_on}\t{item.company}\t{item.title}\t{item.url}",
                flush=True,
            )
        return 0 if errors == 0 else 1

    written = sheets.append_releases(curated)
    logger.info("Wrote %s curated releases (%s fetch/curate errors)", written, errors)
    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Curate pharma/biotech press releases")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only ensure spreadsheet schema and seed companies sheet",
    )
    args = parser.parse_args(argv)
    return run(seed_only=args.seed_only)


if __name__ == "__main__":
    sys.exit(main())
