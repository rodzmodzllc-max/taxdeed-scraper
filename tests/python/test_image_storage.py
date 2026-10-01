"""Storage-optimization sprint (2026-10-01): image priority, optimization,
exact deduplication, the fail-closed budget, and the in-place optimizer.
"""
from __future__ import annotations

import importlib
import io
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import image_storage as IS  # noqa: E402

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

WORKFLOW = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")


def aerial_png(seed: int = 1, size=(600, 450)) -> bytes:
    """A synthetic stand-in for a NAIP tile: smooth fields plus texture, the
    way an aerial image of lots and canopy looks to an encoder."""
    rnd = random.Random(seed)
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            base = (x // 40 + y // 30) % 3
            n = rnd.randint(-18, 18)
            px[x, y] = (60 + base * 40 + n, 90 + base * 25 + n, 50 + base * 10 + n)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(scope="module")
def png():
    return aerial_png()


def _naip(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    sys.modules.pop("enrich_property_photos_naip", None)
    return importlib.import_module("enrich_property_photos_naip")


def _run_naip(monkeypatch, naip, *, used=0, tiers_rows=None, exists=lambda p: False, image=None, put=None):
    """Drive main() with fakes; returns (report, uploads, patches, requested sources)."""
    image = image or aerial_png(3)
    monkeypatch.setattr(naip, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: used)
    tiers_rows = tiers_rows or {"eq.laft": 2, "eq.auction": 2}
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda flt=None: [(("FL", "Bay"), tiers_rows.get(flt["source"], 0))])
    seen, uploads, patches, reports = [], [], [], []

    def batch(unit, limit, outstanding=None, flt=None):
        seen.append((flt["source"], flt["status"]))
        return [{"id": f"{flt['source']}-{i}", "latitude": 30, "longitude": -85} for i in range(min(limit, tiers_rows.get(flt["source"], 0)))]
    monkeypatch.setattr(naip, "fetch_county_batch", batch)
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: (image, True))
    monkeypatch.setattr(naip, "object_exists", exists)
    monkeypatch.setattr(naip, "put_object", lambda path, data, ct: uploads.append((path, len(data), ct)) or (put(path, data, ct) if put else True))
    monkeypatch.setattr(naip, "patch_property", lambda pid, fields: patches.append((pid, fields)))
    monkeypatch.setattr(naip, "write_priority_report", reports.append)
    assert naip.main() == 0
    return reports[0], uploads, patches, seen


# 1, 2, 3 - priority and certificate exclusion
def test_s01_available_is_collected_before_active_auctions(monkeypatch):
    naip = _naip(monkeypatch)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 2)
    report, uploads, patches, seen = _run_naip(monkeypatch, naip)
    assert [s for s, _ in seen] == ["eq.laft"]                     # the whole batch went to Available
    assert report["tiers"]["available"]["stored"] == 2 and report["tiers"]["auction_active"]["stored"] == 0


def test_s02_active_auctions_before_closed_and_closed_never_collected(monkeypatch):
    naip = _naip(monkeypatch)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 50)
    report, uploads, patches, seen = _run_naip(monkeypatch, naip)
    assert [s for s, _ in seen] == ["eq.laft", "eq.auction"]      # closed auctions requested never
    assert all(not st.startswith("in.") for _, st in seen)
    closed = report["tiers"]["auction_closed"]
    assert closed["collected"] is False and closed["stored"] == 0 and closed["deferred"] == closed["outstanding"]


def test_s03_certificates_never_request_imagery(monkeypatch):
    naip = _naip(monkeypatch)
    assert all(flt["source"] != "eq.certificate" for _, flt in naip.IMAGERY_TIERS)
    with pytest.raises(AssertionError):
        naip.tier_params({"source": "eq.certificate"})
    assert naip.COLLECTED_TIERS == ("available", "auction_active")


# 4, 12 - the 950 MB ceiling stays fail-closed and stops low-priority imagery
def test_s04_ceiling_stops_lower_priority_uploads(monkeypatch):
    naip = _naip(monkeypatch)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 50)
    one = len(IS.optimize_image(aerial_png(3)).data)
    budget = int(naip.STORAGE_BUDGET_MB * 1048576)
    report, uploads, patches, seen = _run_naip(monkeypatch, naip, used=budget - int(one * 1.5))
    assert len(uploads) == 1 and report["tiers"]["available"]["stored"] == 1      # room for exactly one image
    assert report["tiers"]["auction_active"]["stored"] == 0


def test_s12_budget_unknown_or_reached_uploads_nothing(monkeypatch):
    naip = _naip(monkeypatch)
    assert naip.STORAGE_BUDGET_MB == 950
    for used in (None, int(950 * 1048576)):
        report, uploads, patches, seen = _run_naip(monkeypatch, naip, used=used)
        assert uploads == [] and patches == [] and report["uploads_allowed"] is False


# 5 - storage never blocks the structured harvest
def test_s05_imagery_steps_cannot_fail_the_structured_jobs():
    for name in ("- name: Backfill property imagery (USDA NAIP aerial)", "- name: NAIP aerial imagery backfill"):
        block = WORKFLOW[WORKFLOW.index(name):WORKFLOW.index(name) + 600]
        assert "continue-on-error: true" in block, name
    deeds = WORKFLOW[WORKFLOW.index("\n  deeds:"):WORKFLOW.index("\n  certificates:")]
    assert deeds.index("Backfill property imagery (USDA NAIP aerial)") > deeds.index("./scripts/sync-to-supabase.ps1") if "./scripts/sync-to-supabase.ps1" in deeds else True
    assert "pip install requests pillow" in deeds


# 6 - deferred / failed imagery is never marked complete
def test_s06_failed_upload_leaves_the_row_unchecked(monkeypatch):
    naip = _naip(monkeypatch)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 1)
    monkeypatch.setattr(naip, "put_object", lambda *a: False)
    image = aerial_png(4)
    monkeypatch.setattr(naip, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda flt=None: [(("FL", "Bay"), 1)])
    monkeypatch.setattr(naip, "fetch_county_batch", lambda unit, limit, o=None, flt=None: [{"id": "x", "latitude": 30, "longitude": -85}])
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: (image, True))
    monkeypatch.setattr(naip, "object_exists", lambda p: False)
    patches, reports = [], []
    monkeypatch.setattr(naip, "patch_property", lambda pid, f: patches.append(f))
    monkeypatch.setattr(naip, "write_priority_report", reports.append)
    naip.main()
    assert patches == [] and reports[0]["tiers"]["available"]["failed"] == 1 and reports[0]["tiers"]["available"]["deferred"] == 1


# 7, 8 - exact deduplication
def test_s07_identical_images_resolve_to_one_content_addressed_object(png):
    a, b = IS.optimize_image(png), IS.optimize_image(bytes(png))
    other = IS.optimize_image(aerial_png(2))
    assert IS.optimized_path(a.source_sha256) == IS.optimized_path(b.source_sha256)
    assert IS.optimized_path(a.source_sha256) != IS.optimized_path(other.source_sha256)
    groups = IS.consolidation_groups([{"name": "naip/1.png", "etag": "e1", "size": 5}, {"name": "naip/2.png", "etag": "e1", "size": 5},
                                      {"name": "naip/3.png", "etag": "e1", "size": 6}, {"name": "naip/4.png", "etag": "", "size": 5},
                                      {"name": "naip/5.png", "etag": "", "size": 5}])
    assert [sorted(o["name"] for o in g) for g in groups if len(g) > 1] == [["naip/1.png", "naip/2.png"]]   # size and etag must both match; no etag never groups


def test_s08_duplicate_upload_reuses_the_object_and_every_row_points_at_it(monkeypatch):
    naip = _naip(monkeypatch)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 50)
    stored = set()
    report, uploads, patches, seen = _run_naip(monkeypatch, naip, exists=lambda p: p in stored, tiers_rows={"eq.laft": 3, "eq.auction": 0},
                                               put=lambda path, data, ct: stored.add(path) or True)
    urls = {f["photo_url"] for _, f in patches}
    assert len(patches) == 3 and len(urls) == 1 and len(stored) == 1
    assert report["deduplicated"] == 2 and report["compressed"] == 1
    assert next(iter(urls)).endswith(".webp") and "/naip/v2/" in next(iter(urls))


def test_s08b_consolidation_deletes_only_after_references_reach_zero(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    sys.modules.pop("optimize_stored_images", None)
    opt = importlib.import_module("optimize_stored_images")
    data = aerial_png(5)
    blobs = {"naip/a.png": data, "naip/b.png": data, "naip/c.png": aerial_png(6)}
    refs = {opt.public_url(k): 1 for k in blobs}
    repointed, deleted = [], []
    monkeypatch.setattr(opt, "download", lambda p: blobs[p])

    def repoint(old, new):
        repointed.append((old, new)); refs[new] = refs.get(new, 0) + refs.pop(old, 0); return 1
    monkeypatch.setattr(opt, "repoint", repoint)
    monkeypatch.setattr(opt, "refs_to", lambda url: refs.get(url, 0))
    monkeypatch.setattr(opt, "delete_objects", lambda paths: deleted.extend(paths) or True)
    objs = [{"name": k, "etag": "same" if k != "naip/c.png" else "same", "size": len(v), "mimetype": "image/png"} for k, v in blobs.items()]
    rows = [{"photo_url": opt.public_url(k)} for k in blobs]
    res = opt.consolidate(objs, rows)
    assert deleted == ["naip/b.png"] and repointed == [(opt.public_url("naip/b.png"), opt.public_url("naip/a.png"))]
    assert refs[opt.public_url("naip/a.png")] == 2 and opt.public_url("naip/c.png") in refs     # different bytes never merged
    # A reference that survives the repoint keeps the object.
    deleted.clear()
    monkeypatch.setattr(opt, "refs_to", lambda url: 1)
    opt.consolidate(objs, rows)
    assert deleted == []


# 9, 11 - optimized images are displayable and never larger
def test_s09_optimized_image_decodes_at_the_same_dimensions(png):
    o = IS.optimize_image(png)
    assert o.optimized and o.content_type == "image/webp"
    fmt, w, h, colours = IS.probe(o.data)
    assert (fmt, w, h) == ("WEBP", 600, 450) and colours >= IS.MIN_DISTINCT_COLOURS
    assert len(o.data) < 0.5 * len(png)                              # material saving on aerial-like content


def test_s11_never_replaced_by_a_larger_or_broken_file(monkeypatch):
    tiny = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(tiny, format="PNG")
    o = IS.optimize_image(tiny.getvalue())
    assert (o.optimized is False and o.data == tiny.getvalue()) or len(o.data) < len(tiny.getvalue())
    junk = IS.optimize_image(b"not an image")
    assert junk.optimized is False and junk.data == b"not an image"
    monkeypatch.setattr(IS, "WEBP_QUALITY", 100)
    big = IS.optimize_image(aerial_png(7, size=(64, 48)))
    assert big.optimized is False or len(big.data) < len(aerial_png(7, size=(64, 48)))


# 10 - idempotent
def test_s10_re_running_changes_nothing(monkeypatch, png):
    once = IS.optimize_image(png)
    twice = IS.optimize_image(once.data)
    assert twice.optimized is False and twice.data == once.data and twice.reason == "already WebP"
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    sys.modules.pop("optimize_stored_images", None)
    opt = importlib.import_module("optimize_stored_images")
    store = {"naip/a.png": png}
    mime = {"naip/a.png": "image/png"}
    monkeypatch.setattr(opt, "download", lambda p: store.get(p))

    def upload(path, data, ct, upsert):
        store[path] = data; mime[path] = ct; return True
    monkeypatch.setattr(opt, "upload", upload)
    objs = lambda: [{"name": k, "size": len(v), "etag": "x", "mimetype": mime[k]} for k, v in store.items()]  # noqa: E731
    first = opt.compress_in_place(objs(), None)
    after_first = dict(store)
    second = opt.compress_in_place(objs(), None)
    assert first["counts"]["optimized"] == 1 and first["bytes_saved"] > 0
    assert second["counts"] == {"already_optimized": 1} and store == after_first


def test_s10b_failed_verification_restores_the_original(monkeypatch, png):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    sys.modules.pop("optimize_stored_images", None)
    opt = importlib.import_module("optimize_stored_images")
    store = {"naip/a.png": png}
    reads = []

    def download(p):
        reads.append(p)
        return store[p] if len(reads) == 1 else b"corrupted"          # the read-back after upload is wrong
    monkeypatch.setattr(opt, "download", download)
    monkeypatch.setattr(opt, "upload", lambda path, data, ct, upsert: store.__setitem__(path, data) or True)
    res = opt.compress_in_place([{"name": "naip/a.png", "size": len(png), "etag": "x", "mimetype": "image/png"}], None)
    assert res["counts"] == {"already_optimized": 0, "verify_failed_restored": 1} and store["naip/a.png"] == png


# 13 - publication / acquisition semantics untouched
def test_s13_storage_code_touches_no_publication_or_acquisition_field():
    for name in ("image_storage.py", "optimize_stored_images.py", "enrich_property_photos_naip.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for field in ("publication_status", "purchase_path", "acquisition", "inventory_status", "ledger_type", "delisted_at"):
            assert field not in src, (name, field)
    opt_src = (ROOT / "scripts/optimize_stored_images.py").read_text(encoding="utf-8")
    assert opt_src.count('json={"photo_url": new_url}') == 1                 # the only row write, consolidation only
    assert '"--consolidate"' in opt_src and "default=None" in opt_src


def test_s14_storage_job_is_manual_and_reports_counts_only():
    job = WORKFLOW[WORKFLOW.index("\n  storage:"):]
    assert "github.event.inputs.job == 'storage'" in job and "github.event.schedule" not in job
    assert "out/public/\n            out/private/" in job and "pip install requests pillow" in job
    assert "artifact_evidence.py --job image-storage" in job
    assert "options: [analyze, apply, apply_consolidate]" in WORKFLOW


def test_s15_policy_projection_orders_available_first():
    objs = [{"name": f"naip/{i}.png", "etag": "dup" if i < 3 else f"e{i}", "size": 1000} for i in range(10)]
    p = IS.project_policies(objs, sample_ratio=0.2, budget_bytes=3000, outstanding={"available": 5, "auction_active": 9, "auction_closed": 4, "certificate": 7},
                            avg_new_bytes=200)
    assert p["A_unchanged"] == 10000 and p["B_compress"] == 2000 and p["C_compress_dedup"] == 1600
    assert p["D_plan"]["available"]["would_store"] == 5 and p["D_plan"]["auction_active"]["would_store"] == 2
    assert p["D_plan"]["auction_closed"]["would_store"] == 0 and p["D_plan"]["certificate"]["would_store"] == 0
