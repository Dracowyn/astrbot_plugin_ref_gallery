"""Gallery.scan：目录扫描、manifest 合并、损坏降级、增删统计。"""

import json

import pytest

from astrbot_plugin_ref_gallery.gallery import Gallery


@pytest.fixture
def gallery_root(tmp_path):
    root = tmp_path / "gallery"
    for cat in ("ref", "commission", "daily"):
        (root / cat).mkdir(parents=True)
    (root / "ref" / "main.png").write_bytes(b"png")
    (root / "ref" / "feral.jpg").write_bytes(b"jpg")
    (root / "commission" / "gift.webp").write_bytes(b"webp")
    (root / "daily" / "note.txt").write_text("非图片，应被忽略")
    return root


def test_scan_finds_images_and_categories(gallery_root):
    g = Gallery(gallery_root)
    added, removed = g.scan()
    assert (added, removed) == (3, 0)
    assert g.categories() == {"ref": 2, "commission": 1}
    entry = next(e for e in g.entries if e.rel_path == "ref/main.png")
    assert entry.category == "ref"
    assert entry.rating == "safe"
    assert entry.title == "" and entry.artist == "" and entry.tags == ()
    assert entry.abs_path == gallery_root / "ref" / "main.png"


def test_scan_merges_manifest(gallery_root):
    (gallery_root / "manifest.json").write_text(
        json.dumps(
            {
                "images": {
                    "commission/gift.webp": {
                        "title": "生贺",
                        "artist": "SomeWolf",
                        "tags": ["anthro", "全身"],
                        "rating": "nsfw",
                    }
                }
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    g = Gallery(gallery_root)
    g.scan()
    e = next(x for x in g.entries if x.rel_path == "commission/gift.webp")
    assert (e.title, e.artist, e.tags, e.rating) == (
        "生贺", "SomeWolf", ("anthro", "全身"), "nsfw",
    )
    assert g.manifest_degraded is False


def test_invalid_manifest_values_fall_back(gallery_root):
    (gallery_root / "manifest.json").write_text(
        json.dumps(
            {"images": {"ref/main.png": {"rating": "explicit", "tags": "不是列表"}}},
            ensure_ascii=False,
        ),
        "utf-8",
    )
    g = Gallery(gallery_root)
    g.scan()
    e = next(x for x in g.entries if x.rel_path == "ref/main.png")
    assert e.rating == "safe"
    assert e.tags == ()


def test_broken_manifest_degrades_not_crash(gallery_root):
    (gallery_root / "manifest.json").write_text("{broken json", "utf-8")
    g = Gallery(gallery_root)
    added, _ = g.scan()
    assert added == 3
    assert g.manifest_degraded is True


def test_rescan_counts_added_and_removed(gallery_root):
    g = Gallery(gallery_root)
    g.scan()
    (gallery_root / "ref" / "main.png").unlink()
    (gallery_root / "daily" / "new.gif").write_bytes(b"gif")
    added, removed = g.scan()
    assert (added, removed) == (1, 1)


def test_scan_missing_root_yields_empty(tmp_path):
    g = Gallery(tmp_path / "不存在")
    assert g.scan() == (0, 0)
    assert g.entries == ()


def test_category_dirs_includes_empty_dirs(gallery_root):
    (gallery_root / "extra").mkdir()          # 空类别目录
    (gallery_root / ".hidden").mkdir()        # 隐藏目录应被忽略
    g = Gallery(gallery_root)
    g.scan()
    # daily 目录里只有非图片文件,categories() 不含它,但 category_dirs() 必须含
    assert g.category_dirs() == ["commission", "daily", "extra", "ref"]
    assert "daily" not in g.categories()


def test_category_dirs_missing_root(tmp_path):
    assert Gallery(tmp_path / "不存在").category_dirs() == []
