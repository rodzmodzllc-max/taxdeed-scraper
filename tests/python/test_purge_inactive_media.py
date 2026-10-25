"""The purge plans release only for inactive rows, and never removes an object
that an active row still points at."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("purge", ROOT / "scripts" / "purge_inactive_property_media.py")
purge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(purge)

BUCKET = "property-photos"
URL = "https://x.supabase.co/storage/v1/object/public/property-photos/naip/v2/"


def row(pid, status="active", delisted_at=None, photo=None):
    return {"id": pid, "status": status, "delisted_at": delisted_at,
            "photo_url": (URL + photo) if photo else photo}


def test_closed_dropped_and_delisted_rows_are_released():
    rows = [
        row(1, "closed", photo="a.webp"),
        row(2, "dropped", photo="b.webp"),
        row(3, "active", delisted_at="2026-10-01T00:00:00Z", photo="c.webp"),
        row(4, "active", photo="d.webp"),
    ]
    out = purge.plan(rows, boundary_ids={1, 4}, bucket=BUCKET)
    assert out["clear_photo_ids"] == [1, 2, 3]
    assert out["delete_boundary_ids"] == [1]
    assert out["delete_storage_paths"] == ["naip/v2/a.webp", "naip/v2/b.webp", "naip/v2/c.webp"]


def test_an_object_shared_with_an_active_row_is_kept():
    rows = [row(1, "closed", photo="shared.webp"), row(2, "active", photo="shared.webp")]
    out = purge.plan(rows, boundary_ids=set(), bucket=BUCKET)
    assert out["clear_photo_ids"] == [1]
    assert out["delete_storage_paths"] == []
    assert out["kept_shared_objects"] == 1


def test_active_rows_are_never_touched():
    rows = [row(1, "active", photo="keep.webp"), row(2, "available", photo="keep2.webp")]
    out = purge.plan(rows, boundary_ids={1, 2}, bucket=BUCKET)
    assert out == {"clear_photo_ids": [], "delete_boundary_ids": [],
                   "delete_storage_paths": [], "kept_shared_objects": 0}


def test_unchecked_and_checked_none_rows_are_not_written():
    rows = [row(1, "closed", photo=None), row(2, "closed", photo="")]
    out = purge.plan(rows, boundary_ids=set(), bucket=BUCKET)
    assert out["clear_photo_ids"] == []


def test_a_url_that_is_not_ours_is_cleared_but_not_deleted():
    rows = [{"id": 1, "status": "closed", "delisted_at": None,
             "photo_url": "https://elsewhere.example/img.jpg"}]
    out = purge.plan(rows, boundary_ids=set(), bucket=BUCKET)
    assert out["clear_photo_ids"] == [1]
    assert out["delete_storage_paths"] == []


def test_storage_path_strips_query_string():
    assert purge.storage_path(URL + "x.webp?v=2", BUCKET) == "naip/v2/x.webp"
