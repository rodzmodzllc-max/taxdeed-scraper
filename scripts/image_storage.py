"""Image storage efficiency (storage-optimization sprint, 2026-10-01).

Pure helpers shared by the NAIP backfill (scripts/enrich_property_photos_naip.py)
and the existing-image optimizer (scripts/optimize_stored_images.py). No network
I/O lives here, so every rule is testable offline.

WHAT IS STORED, AND WHY

NAIP aerial imagery arrives as a lossless PNG (600 x 450, ~290 KB). The app
shows it at that size or smaller (card banner, property-page hero, map
preview), so the dimensions are kept exactly. Only the encoding changes: the
pixels are re-encoded as WebP, quality 82. The result still shows the parcel,
its structures, its frontage and the surrounding lots.
`optimize_image()` refuses any result that fails one of these checks:

  * it cannot be decoded back;
  * its dimensions differ from the source;
  * it is not strictly smaller than the source;
  * it is a near-blank image (a decode that collapsed to one colour).

On a refusal, the original bytes are stored unchanged. An image is never
replaced by a larger or broken one.

CONTENT-ADDRESSED PATHS = EXACT DEDUPLICATION

An optimized image is stored at `naip/v2/<sha256 of the SOURCE bytes>.webp`.
Two properties whose source images are byte-identical (the same coordinates
return the same NAIP tile, e.g. 151 Miami-Dade certificates geocoded to one
point) resolve to ONE object. Visually similar but different images have
different hashes and are never merged. The key is the source hash, not the
WebP hash, so the result does not depend on the encoder being deterministic.

EXISTING OBJECTS ARE RE-ENCODED IN PLACE

scripts/optimize_stored_images.py rewrites an existing object at its OWN path
(same URL), so no `properties` row is written. Every UPDATE on `properties`
bumps `updated_at`, which the app shows as "Last synced"; repointing rows
would falsely mark thousands of rows freshly synced.

IDEMPOTENCE

A WebP input is returned untouched, and an object whose stored MIME type is
image/webp is skipped. Running the optimizer twice changes nothing.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

OPTIMIZED_PREFIX = "naip/v2/"
LEGACY_PREFIX = "naip/"
WEBP_QUALITY = 82
WEBP_METHOD = 6
# A legitimate aerial tile always has texture. A decode whose colour spread
# collapsed (fewer than this many distinct colours in a 64 x 48 sample) is
# treated as broken, never stored as an "optimized" image.
MIN_DISTINCT_COLOURS = 16

# Imagery priority (Available > active auctions > closed auctions; no new
# imagery for certificates). Ranks are used by the reports and tests.
PRIORITY = {"available": 1, "auction_active": 2, "auction_closed": 3, "certificate": 4}
GONE = frozenset({"closed", "expired", "gone", "sold", "redeemed", "cancelled", "canceled"})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tier_of(source: str | None, status: str | None) -> str:
    """The imagery tier a property row belongs to."""
    gone = str(status or "active").lower() in GONE
    if source == "laft":
        return "available" if not gone else "available_closed"
    if source == "auction":
        return "auction_closed" if gone else "auction_active"
    if source == "certificate":
        return "certificate"
    return "unknown"


def optimized_path(source_sha256: str) -> str:
    return f"{OPTIMIZED_PREFIX}{source_sha256}.webp"


def object_path_of(url: str | None, bucket: str = "property-photos") -> str | None:
    """The bucket-relative object path of a public storage URL, or None."""
    marker = f"/{bucket}/"
    if not url or marker not in url:
        return None
    return url.split(marker, 1)[1].split("?", 1)[0]


def is_optimized(url_or_path: str | None) -> bool:
    if not url_or_path:
        return False
    path = object_path_of(url_or_path) or url_or_path
    return path.startswith(OPTIMIZED_PREFIX) and path.endswith(".webp")


@dataclass(frozen=True)
class Optimized:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int
    source_sha256: str
    source_bytes: int
    optimized: bool          # False = the source bytes are stored unchanged
    reason: str = ""

    @property
    def saved_bytes(self) -> int:
        return max(0, self.source_bytes - len(self.data))


def _image():
    try:
        from PIL import Image  # noqa: WPS433 - optional dependency, checked at call time
        return Image
    except ImportError:
        return None


def probe(data: bytes):
    """(format, width, height, distinct colours in a small sample) or None if undecodable."""
    Image = _image()
    if Image is None or not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = (im.format or "").upper()
            w, h = im.size
            sample = im.convert("RGB").resize((64, 48))
            pixels = sample.get_flattened_data() if hasattr(sample, "get_flattened_data") else sample.getdata()
            colours = len(set(pixels))
            return fmt, w, h, colours
    except Exception:  # noqa: BLE001 - any decode failure means "not displayable"
        return None


def _unchanged(data: bytes, reason: str, fmt: str = "PNG", w: int = 0, h: int = 0) -> Optimized:
    ext = "webp" if fmt == "WEBP" else "png"
    return Optimized(data, f"image/{ext}", ext, w, h, sha256(data), len(data), False, reason)


def optimize_image(data: bytes) -> Optimized:
    """Re-encode a source image as same-size WebP when that is strictly smaller
    and decodes cleanly; otherwise return the source bytes unchanged."""
    src = probe(data)
    if src is None:
        return _unchanged(data, "source not decodable (Pillow missing or corrupt bytes)")
    fmt, w, h, colours = src
    if fmt == "WEBP":
        return _unchanged(data, "already WebP", fmt, w, h)
    Image = _image()
    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = im.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
            webp = out.getvalue()
    except Exception as exc:  # noqa: BLE001
        return _unchanged(data, f"encode failed: {type(exc).__name__}", fmt, w, h)
    check = probe(webp)
    if check is None:
        return _unchanged(data, "optimized bytes did not decode", fmt, w, h)
    _, ow, oh, ocolours = check
    if (ow, oh) != (w, h):
        return _unchanged(data, "optimized dimensions differ", fmt, w, h)
    if len(webp) >= len(data):
        return _unchanged(data, "optimized file not smaller", fmt, w, h)
    if colours >= MIN_DISTINCT_COLOURS and ocolours < MIN_DISTINCT_COLOURS:
        return _unchanged(data, "optimized image lost its detail", fmt, w, h)
    return Optimized(webp, "image/webp", "webp", w, h, sha256(data), len(data), True)


def consolidation_groups(objects: list[dict]) -> list[list[dict]]:
    """Group storage objects whose CONTENT is identical.

    `objects` carry `name`, `etag` (the storage MD5) and `size`. Objects are
    only candidates when both match; callers must still confirm byte identity
    (sha256 of the downloaded bytes) before consolidating - an etag match
    alone is never treated as proof.
    """
    groups: dict[tuple, list[dict]] = {}
    for o in objects:
        key = (str(o.get("etag") or "").strip('"'), int(o.get("size") or 0))
        if not key[0]:
            key = ("name:" + str(o.get("name")), key[1])     # no etag: never grouped with another object
        groups.setdefault(key, []).append(o)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0].get("name") or ""))


def project_policies(objects: list[dict], *, sample_ratio: float, budget_bytes: int,
                     outstanding: dict[str, int] | None = None, avg_new_bytes: int | None = None) -> dict:
    """Projected bucket size under the four policies.

    A - unchanged; B - same-size WebP re-encode (sample_ratio = measured
    optimized/source size); C - B plus exact deduplication; D - C plus new
    imagery collected in priority order (Available, then active auctions)
    until the budget, closed auctions and certificates deferred.
    """
    total = sum(int(o.get("size") or 0) for o in objects)
    groups = consolidation_groups(objects)
    unique_total = sum(int(g[0].get("size") or 0) for g in groups)
    b = int(total * sample_ratio)
    c = int(unique_total * sample_ratio)
    d_plan = {}
    room = max(0, budget_bytes - c)
    per = int(avg_new_bytes or (c / max(1, len(groups))))
    for tier in ("available", "auction_active", "auction_closed", "certificate"):
        want = (outstanding or {}).get(tier, 0) if tier in ("available", "auction_active") else 0
        can = min(want, room // per if per else 0)
        d_plan[tier] = {"outstanding": (outstanding or {}).get(tier, 0), "would_store": can,
                        "would_defer": (outstanding or {}).get(tier, 0) - can}
        room -= can * per
    return {"A_unchanged": total, "B_compress": b, "C_compress_dedup": c,
            "D_compress_dedup_priority": c + sum(v["would_store"] for v in d_plan.values()) * per,
            "D_plan": d_plan, "objects": len(objects), "unique_contents": len(groups)}
