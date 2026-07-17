from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from .companies import load_companies_from_yaml
from .curator import Curator
from .dedupe import release_fingerprint
from .detail import extract_release_detail
from .extractors import fetch_company_releases, fetch_tdnet_releases
from .http_client import HttpClient
from .models import Company, CuratedRelease, RawRelease
from .settings import load_settings
from .sheets_client import SheetsClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("pr-disclosure-curator")


def _fingerprint_for_raw(raw: RawRelease) -> str:
    return release_fingerprint(raw.company, raw.published_on, raw.title)


def _process_raw_items(
    raw_items: list[RawRelease],
    *,
    http: HttpClient,
    curator: Curator,
    cutoff: date,
    existing_urls: set[str],
    seen_fingerprints: set[str],
    reprocess_existing: bool,
    curated: list[CuratedRelease],
) -> int:
    errors = 0
    for raw in raw_items:
        is_existing_url = raw.url in existing_urls
        if is_existing_url and not reprocess_existing:
            continue
        if raw.published_on and raw.published_on < cutoff and not is_existing_url:
            continue
        fingerprint = _fingerprint_for_raw(raw)
        if fingerprint in seen_fingerprints and not is_existing_url:
            logger.info(
                "Skip duplicate %s | %s (%s)",
                raw.company,
                raw.title,
                raw.source_type,
            )
            continue
        try:
            detail = extract_release_detail(raw, http)
            if detail.published_on:
                raw.published_on = detail.published_on
                fingerprint = _fingerprint_for_raw(raw)
                if fingerprint in seen_fingerprints and not is_existing_url:
                    logger.info(
                        "Skip duplicate %s | %s (%s)",
                        raw.company,
                        raw.title,
                        raw.source_type,
                    )
                    continue
            item = curator.curate(
                raw,
                detail.paragraph,
                reference_url=detail.reference_url,
            )
        except Exception:
            logger.exception("Failed to curate: %s", raw.url)
            errors += 1
            continue
        if item is None:
            continue
        item_fingerprint = release_fingerprint(
            item.company,
            item.published_on,
            item.original_title or item.title,
        )
        if item_fingerprint in seen_fingerprints and not is_existing_url:
            logger.info(
                "Skip duplicate %s | %s (%s)",
                item.company,
                item.title,
                raw.source_type,
            )
            continue
        curated.append(item)
        existing_urls.add(item.url)
        seen_fingerprints.add(fingerprint)
        seen_fingerprints.add(item_fingerprint)
        logger.info("KEEP %s | %s", item.company, item.title)
    return errors


def run(seed_only: bool = False, reprocess_existing: bool = False) -> int:
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
    synced = sheets.sync_companies(yaml_companies)
    if synced["appended"] or synced["updated_codes"]:
        logger.info(
            "Synced companies sheet (appended=%s, stock_codes_filled=%s)",
            synced["appended"],
            synced["updated_codes"],
        )

    if seed_only:
        return 0

    locally_disabled = {company.name for company in yaml_companies if not company.enabled}
    yaml_by_name = {company.name: company for company in yaml_companies}
    companies: list[Company] = []
    for company in sheets.load_companies():
        if not company.enabled or company.name in locally_disabled:
            continue
        yaml_company = yaml_by_name.get(company.name)
        if yaml_company:
            updates: dict = {}
            if yaml_company.config:
                # Repo YAML is the source of truth for extractor selectors/tuning.
                updates["config"] = yaml_company.config
            if yaml_company.stock_code and not company.stock_code:
                updates["stock_code"] = yaml_company.stock_code
            elif yaml_company.stock_code:
                # Prefer repo stock codes when present.
                updates["stock_code"] = yaml_company.stock_code
            if updates:
                company = company.model_copy(update=updates)
        companies.append(company)
    if not companies:
        # Fallback to local YAML if sheet unexpectedly empty after seed attempt
        companies = [c for c in yaml_companies if c.enabled]
        logger.warning("Using local YAML companies (%s)", len(companies))

    existing_urls, seen_fingerprints = sheets.existing_release_keys()
    http = HttpClient(settings.user_agent, settings.request_timeout_seconds)
    curator = Curator(settings)
    cutoff = date.today() - timedelta(days=settings.lookback_days)

    curated: list[CuratedRelease] = []
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

            errors += _process_raw_items(
                raw_items,
                http=http,
                curator=curator,
                cutoff=cutoff,
                existing_urls=existing_urls,
                seen_fingerprints=seen_fingerprints,
                reprocess_existing=reprocess_existing,
                curated=curated,
            )

        logger.info(
            "Crawling TDnet (lookback=%s days)", settings.tdnet_lookback_days
        )
        try:
            tdnet_items = fetch_tdnet_releases(
                companies,
                http,
                lookback_days=settings.tdnet_lookback_days,
                max_items_per_company=settings.max_items_per_company,
            )
        except Exception:
            logger.exception("Failed to fetch TDnet disclosures")
            errors += 1
            tdnet_items = []

        errors += _process_raw_items(
            tdnet_items,
            http=http,
            curator=curator,
            cutoff=cutoff,
            existing_urls=existing_urls,
            seen_fingerprints=seen_fingerprints,
            reprocess_existing=reprocess_existing,
            curated=curated,
        )
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
        if errors:
            logger.warning("Completed with %s non-fatal errors", errors)
        return 0

    written = sheets.upsert_releases(curated)
    logger.info("Upserted %s curated releases (%s fetch/curate errors)", written, errors)
    if errors:
        logger.warning("Completed with %s non-fatal errors", errors)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Curate pharma/biotech press releases")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only ensure spreadsheet schema and seed companies sheet",
    )
    parser.add_argument(
        "--reprocess-existing",
        action="store_true",
        help="Re-extract and update existing URLs in the releases sheet",
    )
    args = parser.parse_args(argv)
    return run(
        seed_only=args.seed_only,
        reprocess_existing=args.reprocess_existing,
    )


if __name__ == "__main__":
    sys.exit(main())
