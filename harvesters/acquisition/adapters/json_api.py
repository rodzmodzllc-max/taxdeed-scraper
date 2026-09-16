"""JSON API adapter - Phase 39 Sections 5, 11, 21.

The reusable adapter for a paginated JSON/REST source. Its first and
currently only configured deployment is `tx_lgbs`
(`taxsales.lgbs.com/api/property_sales/`), which this phase re-verified
live on 2026-09-16 through this session's sanctioned web-fetch path:

  - endpoint answers, DRF-style `count`/`next`/`previous`/`results`
    envelope confirmed unchanged;
  - `count` = 6,309 rows for `area=TX` at time of check;
  - all 29 result fields confirmed present, including every field
    `harvest_lgbs()` reads: `state`, `county`, `status`, `account_nbr`,
    `cause_nbr`, `sale_date_only`, `minimum_bid`, `value`, `sale_notes`,
    `prop_address_one`, `prop_city`, `prop_zipcode`, `geometry`.

**This adapter does not reimplement LGBS parsing.** It calls the existing,
production-proven, already-tested normalizer helpers in
`harvesters/texas_harvester.py` (`_lgbs_normalize_county`, `_lgbs_to_float`,
`_lgbs_compose_address`, `LGBS_STATUS_TO_LEDGER`) - Phase 39 Section 9/21's
"do not revert or replace working LGBS behavior" and "preserve source
semantics as verified". The only behavior this adapter adds around them is
what the harvester never had: policy checking, structured results,
per-page retrieval metadata, provenance attachment, deduplication and
resumable checkpoints.

One semantic this adapter preserves deliberately and would be wrong to
"simplify": LGBS's `area=TX` query parameter is NOT a strict state filter
(a live sample previously returned Philadelphia County, PA rows
interleaved with Texas ones), so every row's own `state` field is checked.
And per Section 21, ledger classification keys off `status`, never
`sale_type`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..adapter import AdapterConfig, SourceAdapter, deduplicate, utc_now_iso
from ..categories import DataCategory, SourceTier
from ..policy import AcquisitionPurpose
from ..result import (
    AcquisitionResult,
    AcquisitionStatus,
    RetrievalMetadata,
    build_result,
)
from ..transport import SchemaError, TransportError

# Import the existing, verified LGBS normalizers rather than copying them.
_HARVESTERS_DIR = Path(__file__).resolve().parents[2]
if str(_HARVESTERS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARVESTERS_DIR))


def _lgbs_helpers():
    """Late import so that merely importing this module does not pull in
    the whole Texas harvester (which prints to stderr and defines module
    level CSV paths). Keeps the acquisition package importable in isolation
    - the same reason `texas_harvester.main()` imports its own governance
    dependency inside the function body."""
    from texas_harvester import (  # type: ignore
        LGBS_STATUS_TO_LEDGER,
        _lgbs_compose_address,
        _lgbs_normalize_county,
        _lgbs_to_float,
    )

    return LGBS_STATUS_TO_LEDGER, _lgbs_compose_address, _lgbs_normalize_county, _lgbs_to_float


LGBS_CONFIG = AdapterConfig(
    source_id="tx_lgbs",
    state="TX",
    county=None,  # statewide/multi-county by product design
    base_url="https://taxsales.lgbs.com/api/property_sales/",
    categories=(
        DataCategory.AUCTION,
        DataCategory.AUCTION_DATE,
        DataCategory.MINIMUM_BID,
        DataCategory.CASE_NUMBER,
        DataCategory.SALE_STATUS,
        DataCategory.PARCEL_APN,
        DataCategory.ADDRESS,
        DataCategory.LEGAL_DESCRIPTION,
        DataCategory.MARKET_VALUE,
        DataCategory.LATITUDE,
        DataCategory.LONGITUDE,
    ),
    tier=SourceTier.OTHER_PUBLIC_THIRD_PARTY,  # a law firm's public portal, not a government API
    retrieval_method="json_api_paginated",
    query_params={"area": "TX"},
    page_size=500,
    raw_storage_permitted=False,
    notes=(
        "Live re-verified 2026-09-16: envelope and all 29 result fields unchanged; count=6309 for area=TX. "
        "NOTE: the /api/sale_status/ enum endpoint referenced in texas_harvester.py's comments returned "
        "HTTP 404 on the same date - the documented status vocabulary could not be re-confirmed from that "
        "endpoint this phase. LGBS_STATUS_TO_LEDGER is left exactly as verified in 2026-09; see "
        "docs/source-adapters.md."
    ),
)


class JsonApiAdapter(SourceAdapter):
    """Generic paginated-JSON adapter. Subclass hooks: `build_first_url()`,
    `extract_records()`, `next_url()`, `normalize()`."""

    def build_first_url(self) -> str:
        import urllib.parse

        params = dict(self.config.query_params)
        if self.config.page_size:
            params["limit"] = str(self.config.page_size)
        return f"{self.config.base_url}?{urllib.parse.urlencode(params)}"

    def extract_records(self, payload) -> list[dict]:
        if not isinstance(payload, dict):
            raise SchemaError(f"{self.source_id}: expected a JSON object envelope, got {type(payload).__name__}")
        results = payload.get("results")
        if results is None:
            raise SchemaError(f"{self.source_id}: response envelope has no 'results' key (schema change?)")
        if not isinstance(results, list):
            raise SchemaError(f"{self.source_id}: 'results' is {type(results).__name__}, expected a list")
        return results

    def next_url(self, payload) -> str | None:
        url = payload.get("next") if isinstance(payload, dict) else None
        # LGBS's own `next` links come back as plain http:// - upgrade
        # before following so every request after the first stays
        # encrypted. Preserved verbatim from harvest_lgbs().
        if url and url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        return url

    def _acquire(self, *, started_at: str, limit: int | None, checkpoint: dict | None) -> AcquisitionResult:
        url = (checkpoint or {}).get("next_url") or self.build_first_url()
        records: list[dict] = []
        seen = 0
        skipped = 0
        failed = 0
        warnings: list[str] = []
        page = 0
        source_timestamp: str | None = None
        # Phase 41: per-reason skip classification, so a run can report
        # non-TX rejections separately from unmapped-status ones. Reset per
        # acquire() call, never accumulated across runs.
        self._rejections = {}

        # Phase 46. `failure` holds the transport error that interrupted the
        # walk, if any. It is caught HERE rather than allowed to escape to
        # SourceAdapter.acquire()'s handler, because that handler has no
        # access to these locals and therefore builds its result with no
        # records at all - which is how run #3 (35109232214) retrieved a
        # 500-record page and then reported records_seen=0. Every record
        # already retrieved must survive a later page's failure.
        failure: TransportError | None = None

        while url:
            page += 1
            page_started = utc_now_iso()
            try:
                response = self.transport.get(url)
                payload = response.json()
                page_records = self.extract_records(payload)
            except TransportError as exc:
                # `url` is deliberately left pointing at the page that
                # failed, so the checkpoint below resumes by RETRYING it
                # rather than skipping past it. Skipping would silently
                # drop that page's records from any resumed run.
                failure = exc
                break
            source_timestamp = source_timestamp or response.source_updated_at

            page_acquired = 0
            for raw in page_records:
                seen += 1
                try:
                    normalized = self.normalize(raw)
                except Exception as exc:  # a single malformed record must not kill the run
                    failed += 1
                    warnings.append(f"record normalization failed: {type(exc).__name__}: {exc}")
                    continue
                if normalized is None:
                    skipped += 1
                    continue
                records.append(normalized)
                page_acquired += 1
                if limit is not None and len(records) >= limit:
                    break

            self.record_retrieval(
                RetrievalMetadata(
                    source_id=self.source_id,
                    state=self.config.state,
                    county=self.config.county,
                    source_url=url,
                    retrieval_method=self.config.retrieval_method,
                    started_at=page_started,
                    completed_at=utc_now_iso(),
                    http_status=response.http_status,
                    records_seen=len(page_records),
                    records_acquired=page_acquired,
                    records_failed=0,
                    content_type=response.content_type,
                    content_hash_value=response.hash(),
                    source_updated_at=response.source_updated_at,
                )
            )

            if limit is not None and len(records) >= limit:
                break
            url = self.next_url(payload)

        unique, duplicates = deduplicate(records)
        if duplicates:
            warnings.append(f"{duplicates} duplicate record(s) dropped by idempotency key")
            self._rejections["DUPLICATE"] = self._rejections.get("DUPLICATE", 0) + duplicates

        errors: tuple[str, ...] = ()
        if failure is not None:
            # The failure status wins over SUCCESS/PARTIAL_SUCCESS even when
            # records were retrieved. A walk that did not finish is not a
            # success that happens to carry an error - and because this
            # status is in ACQUISITION_FAILURE_STATUSES and NOT in
            # ACQUISITION_PRODUCED_RECORDS, AcquisitionRun.finalize() lands
            # on INCOMPLETE. That is stricter than the PARTIAL a
            # records-carrying success would have produced, not weaker.
            status = failure.status
            errors = (f"{failure.error_code}: {failure}",)
            warnings.append(
                f"page {page} failed after {len(unique)} record(s) had already been retrieved; "
                "those records are retained and the run is not complete"
            )
        elif not unique:
            status = AcquisitionStatus.NO_DATA
        elif failed:
            status = AcquisitionStatus.PARTIAL_SUCCESS
        else:
            status = AcquisitionStatus.SUCCESS

        return build_result(
            source_id=self.source_id,
            jurisdiction=self.jurisdiction,
            status=status,
            started_at=started_at,
            records=unique,
            records_seen=seen,
            records_failed=failed,
            records_skipped=skipped + duplicates,
            categories=tuple(c.value for c in self.categories),
            errors=errors,
            warnings=tuple(warnings),
            source_timestamp=source_timestamp,
            retrieval_method=self.config.retrieval_method,
            retrievals=tuple(self._retrievals),
            raw_storage_status=self._raw_storage_status(),
            checkpoint={"next_url": url} if url else None,
            rejections_by_reason=dict(getattr(self, "_rejections", {})),
        )

    def normalize(self, raw_record: dict) -> dict | None:  # pragma: no cover - overridden
        raise NotImplementedError


class LgbsAdapter(JsonApiAdapter):
    """`tx_lgbs`. Normalization delegates entirely to the existing verified
    helpers in `harvesters/texas_harvester.py`."""

    def __init__(self, transport=None, config: AdapterConfig | None = None):
        super().__init__(config or LGBS_CONFIG, transport)

    def _reject(self, reason: str) -> None:
        """Record WHY a record was skipped. Phase 41 Section 8 requires
        non-TX rejections to be reportable separately; without this the run
        layer can only see an undifferentiated `records_skipped` total."""
        if not hasattr(self, "_rejections"):
            self._rejections = {}
        self._rejections[reason] = self._rejections.get(reason, 0) + 1

    def normalize(self, raw_record: dict) -> dict | None:
        status_to_ledger, compose_address, normalize_county, to_float = _lgbs_helpers()

        # Preserved semantics, verbatim from harvest_lgbs():
        # 1. area=TX is not a strict state filter - check each row's state.
        #    Phase 40 measured this at 2,104 of 6,309 rows (33.4%) being
        #    Philadelphia, PA, so this branch is load-bearing, not defensive.
        if raw_record.get("state") != "TX":
            self._reject("OUT_OF_STATE")
            return None
        # 2. Ledger classification keys off `status`, never `sale_type`.
        ledger = status_to_ledger.get(raw_record.get("status"))
        if ledger is None:
            self._reject("UNMAPPED_STATUS")
            return None

        county = normalize_county(raw_record.get("county"))
        account_number = raw_record.get("account_nbr") or None
        if not county or not account_number:
            self._reject("MISSING_IDENTITY")
            return None

        coords = ((raw_record.get("geometry") or {}).get("coordinates")) or [None, None]
        lon, lat = (list(coords) + [None, None])[:2]

        record = {
            "state": "TX",
            "county": county,
            "account_number": account_number,
            "case_no": account_number,  # matches sync-texas-to-supabase.py's existing mapping
            "parcel": raw_record.get("cause_nbr") or None,
            "cause_number": raw_record.get("cause_nbr") or None,
            "auction_date": raw_record.get("sale_date_only") or None,
            "min_bid": to_float(raw_record.get("minimum_bid")),
            "cad_market_value": to_float(raw_record.get("value")),
            "legal_description": (raw_record.get("sale_notes") or "").strip() or None,
            "address": compose_address(raw_record),
            "latitude": to_float(lat),
            "longitude": to_float(lon),
            "source": ledger,
            "harvester_source": "tx_lgbs",
            # Source-native values preserved alongside normalized ones
            # (Section 28's "preserve original source values where
            # important" / Section 58's conflict handling).
            "_source_status": raw_record.get("status"),
            "_source_sale_type": raw_record.get("sale_type"),
        }
        return self.attach_provenance(
            record,
            source_record_id=str(raw_record.get("uid") or raw_record.get("sale_id") or account_number),
            retrieved_at=utc_now_iso(),
            source_timestamp=raw_record.get("sale_date") or None,
        )
