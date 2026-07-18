from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone, timedelta

from .companies import load_companies_from_yaml
from .curator import Curator
from .dedupe import (
    canonicalize_url,
    content_hash,
    release_fingerprint,
    titles_likely_same,
)
from .detail import extract_release_detail
from .extractors import fetch_company_releases, fetch_tdnet_releases
from .http_client import HttpClient
from .metrics import RunMetrics
from .models import Company, CuratedRelease, DecisionRecord, RawRelease
from .settings import load_settings
from .sheets_client import SheetsClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("pr-disclosure-curator")


def _fingerprint_for_raw(raw: RawRelease) -> str:
    return release_fingerprint(raw.company, raw.published_on, raw.title)


def _merge_company_configs(
    sheet_companies: list[Company],
    yaml_companies: list[Company],
    *,
    shadow_default: bool,
) -> list[Company]:
    """YAML is authority for crawl config; Sheets owns enabled + crawl_mode override."""
    locally_disabled = {c.name for c in yaml_companies if not c.enabled}
    yaml_by_name = {c.name: c for c in yaml_companies}
    companies: list[Company] = []
    for company in sheet_companies:
        if not company.enabled or company.name in locally_disabled:
            continue
        yaml_company = yaml_by_name.get(company.name)
        if yaml_company:
            updates: dict = {
                "list_url": yaml_company.list_url,
                "source_type": yaml_company.source_type,
                "config": yaml_company.config,
            }
            if yaml_company.stock_code:
                updates["stock_code"] = yaml_company.stock_code
            # Prefer sheet crawl_mode when present; else YAML; else settings default.
            if company.crawl_mode:
                updates["crawl_mode"] = company.crawl_mode
            elif yaml_company.crawl_mode:
                updates["crawl_mode"] = yaml_company.crawl_mode
            elif shadow_default:
                updates["crawl_mode"] = "shadow"
            company = company.model_copy(update=updates)
        elif shadow_default and company.crawl_mode == "live":
            company = company.model_copy(update={"crawl_mode": "shadow"})
        companies.append(company)
    return companies


def _cluster_candidates(raw_items: list[RawRelease]) -> list[RawRelease]:
    """Collapse cross-source duplicates before detail fetch / LLM."""
    clusters: list[list[RawRelease]] = []
    for raw in raw_items:
        placed = False
        for cluster in clusters:
            seed = cluster[0]
            if seed.company != raw.company:
                continue
            same_day = (
                seed.published_on is not None
                and raw.published_on is not None
                and seed.published_on == raw.published_on
            ) or (seed.published_on is None or raw.published_on is None)
            if not same_day:
                continue
            if canonicalize_url(seed.url) == canonicalize_url(raw.url):
                cluster.append(raw)
                placed = True
                break
            if titles_likely_same(seed.title, raw.title):
                cluster.append(raw)
                placed = True
                break
        if not placed:
            clusters.append([raw])

    merged: list[RawRelease] = []
    for cluster in clusters:
        # Prefer official site URL over TDnet PDF when both exist.
        preferred = sorted(
            cluster,
            key=lambda item: (
                0 if item.source_type != "tdnet" else 1,
                0 if not item.url.lower().endswith(".pdf") else 1,
                item.url,
            ),
        )[0]
        # Keep alternate as reference when sources differ.
        others = [item for item in cluster if item.url != preferred.url]
        if others and not preferred.reference_url:
            preferred = preferred.model_copy(update={"reference_url": others[0].url})
        # A live source must win for writing even if a shadow source is preferred.
        if any(item.crawl_mode == "live" for item in cluster):
            preferred = preferred.model_copy(update={"crawl_mode": "live"})
        merged.append(preferred)
    return merged


def _source_overlap_stats(raw_items: list[RawRelease], metrics: RunMetrics) -> None:
    by_company: dict[str, list[RawRelease]] = {}
    for item in raw_items:
        by_company.setdefault(item.company, []).append(item)
    for items in by_company.values():
        site = [i for i in items if i.source_type != "tdnet"]
        tdnet = [i for i in items if i.source_type == "tdnet"]
        matched = 0
        for s in site:
            if any(
                titles_likely_same(s.title, t.title)
                or canonicalize_url(s.url) == canonicalize_url(t.url)
                for t in tdnet
            ):
                matched += 1
        metrics.matched_site_tdnet += matched
        metrics.site_only += max(0, len(site) - matched)
        metrics.tdnet_only += max(
            0,
            len(tdnet)
            - sum(
                1
                for t in tdnet
                if any(
                    titles_likely_same(s.title, t.title)
                    or canonicalize_url(s.url) == canonicalize_url(t.url)
                    for s in site
                )
            ),
        )


def _process_raw_items(
    raw_items: list[RawRelease],
    *,
    http: HttpClient,
    curator: Curator,
    cutoff: date,
    existing_urls: set[str],
    seen_fingerprints: set[str],
    decision_cache: dict[str, DecisionRecord],
    decisions_out: list[DecisionRecord],
    reprocess_existing: bool,
    curated: list[CuratedRelease],
    metrics: RunMetrics,
    company_modes: dict[str, str],
    criteria_version: str,
) -> int:
    errors = 0
    for raw in raw_items:
        metrics.candidates_seen += 1
        canonical = canonicalize_url(raw.url)
        is_existing_url = raw.url in existing_urls or canonical in existing_urls
        if is_existing_url and not reprocess_existing:
            metrics.duplicates_skipped += 1
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
            metrics.duplicates_skipped += 1
            continue

        cached = (
            decision_cache.get(fingerprint)
            or decision_cache.get(canonical)
            or decision_cache.get(raw.url)
        )
        if (
            cached
            and cached.decision in {"discard", "hard_discard"}
            and not reprocess_existing
        ):
            metrics.cache_hits += 1
            logger.info(
                "Skip cached %s %s | %s",
                cached.decision,
                raw.company,
                raw.title,
            )
            continue

        metrics.candidates_new += 1
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
                    metrics.duplicates_skipped += 1
                    continue
            body_hash = content_hash(detail.source_text or detail.paragraph)
            if body_hash and body_hash in decision_cache and not reprocess_existing:
                cached_body = decision_cache[body_hash]
                if cached_body.decision in {"discard", "hard_discard"}:
                    metrics.cache_hits += 1
                    continue
            item, decision_meta = curator.curate_with_decision(
                raw,
                detail.paragraph,
                reference_url=detail.reference_url,
                source_text=detail.source_text,
            )
        except Exception:
            logger.exception("Failed to curate: %s", raw.url)
            errors += 1
            metrics.fetch_errors += 1
            continue

        record = DecisionRecord(
            decided_at=datetime.now(timezone.utc),
            company=raw.company,
            published_on=(raw.published_on.isoformat() if raw.published_on else ""),
            title=raw.title,
            url=raw.url,
            canonical_url=canonical,
            fingerprint=fingerprint,
            content_hash=content_hash(detail.source_text or detail.paragraph),
            decision=str(decision_meta.get("decision") or "discard"),
            reason=str(decision_meta.get("reason") or ""),
            source_type=raw.source_type,
            model=str(decision_meta.get("model") or ""),
            criteria_version=str(
                decision_meta.get("criteria_version") or criteria_version
            ),
        )
        decisions_out.append(record)
        for key in (
            record.fingerprint,
            record.canonical_url,
            record.url,
            record.content_hash,
        ):
            if key:
                decision_cache[key] = record

        if item is None:
            continue

        mode = raw.crawl_mode or company_modes.get(raw.company, "live")
        item = item.model_copy(update={"crawl_mode": mode, "source_type": raw.source_type})
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
            metrics.duplicates_skipped += 1
            continue

        if mode == "shadow":
            logger.info("SHADOW KEEP %s | %s", item.company, item.title)
            seen_fingerprints.add(fingerprint)
            seen_fingerprints.add(item_fingerprint)
            continue

        curated.append(item)
        existing_urls.add(item.url)
        if canonical:
            existing_urls.add(canonical)
        seen_fingerprints.add(fingerprint)
        seen_fingerprints.add(item_fingerprint)
        logger.info("KEEP %s | %s", item.company, item.title)
    return errors


def run(
    seed_only: bool = False,
    reprocess_existing: bool = False,
    company_filter: list[str] | None = None,
    since: date | None = None,
    until: date | None = None,
) -> int:
    settings = load_settings()
    yaml_companies = load_companies_from_yaml()
    metrics = RunMetrics()

    if reprocess_existing and not (company_filter or since or until):
        logger.error(
            "--reprocess-existing requires --company and/or --since/--until "
            "to avoid full-sheet rebilling"
        )
        return 2

    if not settings.google_service_account_json:
        logger.error("Google service account credentials are missing")
        return 2

    sheets = SheetsClient(settings)
    sheets.ensure_schema()
    seeded = sheets.seed_companies_if_empty(yaml_companies)
    if seeded:
        logger.info("Seeded %s companies into spreadsheet", seeded)
    synced = sheets.sync_companies(yaml_companies)
    if synced["appended"] or synced.get("updated_fields"):
        logger.info(
            "Synced companies sheet (appended=%s, updated_fields=%s)",
            synced["appended"],
            synced.get("updated_fields", 0),
        )

    if seed_only:
        return 0

    sheet_companies = sheets.load_companies()
    companies = _merge_company_configs(
        sheet_companies,
        yaml_companies,
        shadow_default=settings.shadow_default,
    )
    if not companies:
        companies = [c for c in yaml_companies if c.enabled]
        logger.warning("Using local YAML companies (%s)", len(companies))

    if company_filter:
        wanted = {name.strip() for name in company_filter if name.strip()}
        companies = [c for c in companies if c.name in wanted]
        if not companies:
            logger.error("No companies matched --company filter: %s", company_filter)
            return 2

    company_modes = {c.name: c.crawl_mode for c in companies}
    existing_urls, seen_fingerprints = sheets.existing_release_keys()
    decision_cache = sheets.load_decision_cache()
    http = HttpClient(settings.user_agent, settings.request_timeout_seconds)
    curator = Curator(settings, metrics=metrics)
    cutoff = since or (date.today() - timedelta(days=settings.lookback_days))

    curated: list[CuratedRelease] = []
    decisions_out: list[DecisionRecord] = []
    all_raw: list[RawRelease] = []
    errors = 0
    try:
        for company in companies:
            if company.source_type == "tdnet_only":
                metrics.record_source("tdnet_only", fetched=0)
                continue
            logger.info(
                "Crawling %s (%s, mode=%s)",
                company.name,
                company.source_type,
                company.crawl_mode,
            )
            try:
                raw_items = fetch_company_releases(
                    company, http, limit=settings.max_items_per_company
                )
                metrics.record_source(company.source_type, fetched=len(raw_items))
            except Exception:
                logger.exception("Failed to fetch %s", company.name)
                errors += 1
                metrics.fetch_errors += 1
                metrics.record_source(company.source_type, errors=1)
                continue
            all_raw.extend(raw_items)

        logger.info("Crawling TDnet (lookback=%s days)", settings.tdnet_lookback_days)
        try:
            tdnet_items = fetch_tdnet_releases(
                companies,
                http,
                lookback_days=settings.tdnet_lookback_days,
                max_items_per_company=settings.max_items_per_company,
            )
            metrics.record_source("tdnet", fetched=len(tdnet_items))
        except Exception:
            logger.exception("Failed to fetch TDnet disclosures")
            errors += 1
            metrics.fetch_errors += 1
            metrics.record_source("tdnet", errors=1)
            tdnet_items = []
        all_raw.extend(tdnet_items)

        _source_overlap_stats(all_raw, metrics)
        clustered = _cluster_candidates(all_raw)
        logger.info(
            "Candidates fetched=%s clustered=%s",
            len(all_raw),
            len(clustered),
        )
        if until:
            clustered = [
                item
                for item in clustered
                if not item.published_on or item.published_on <= until
            ]

        errors += _process_raw_items(
            clustered,
            http=http,
            curator=curator,
            cutoff=cutoff,
            existing_urls=existing_urls,
            seen_fingerprints=seen_fingerprints,
            decision_cache=decision_cache,
            decisions_out=decisions_out,
            reprocess_existing=reprocess_existing,
            curated=curated,
            metrics=metrics,
            company_modes=company_modes,
            criteria_version=settings.criteria_version,
        )
    finally:
        http.close()

    curated.sort(key=lambda x: (x.published_on, x.company, x.title), reverse=True)
    for line in metrics.summary_lines():
        logger.info(line)

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

    sheets.append_decisions(decisions_out)
    sheets.append_run_metrics(metrics)
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
        help="Re-extract and update existing URLs (requires --company and/or --since/--until)",
    )
    parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Limit run to company name(s); repeatable",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Only consider items on/after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        default=None,
        help="Only consider items on/before this date (YYYY-MM-DD)",
    )
    args = parser.parse_args(argv)
    return run(
        seed_only=args.seed_only,
        reprocess_existing=args.reprocess_existing,
        company_filter=args.company or None,
        since=args.since,
        until=args.until,
    )


if __name__ == "__main__":
    sys.exit(main())
