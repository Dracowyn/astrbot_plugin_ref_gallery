"""find_by_name 模糊查找 + set_meta 清单写回。"""

import json

import pytest

from astrbot_plugin_ref_gallery.gallery import Gallery, GalleryError


@pytest.fixture
def gallery(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "commission").mkdir()
    (root / "ref" / "main.png").write_bytes(b"a")
    (root / "ref" / "main-2024.png").write_bytes(b"b")
    (root / "commission" / "gift.webp").write_bytes(b"c")
    g = Gallery(root)
    g.scan()
    return g


def test_find_exact_rel_path_wins(gallery):
    # "ref/main.png" 同时是 "main-2024.png" 的子串来源，但精确命中只返回一条
    assert [e.rel_path for e in gallery.find_by_name("ref/main.png")] == ["ref/main.png"]


def test_find_by_filename_substring_case_insensitive(gallery):
    assert [e.rel_path for e in gallery.find_by_name("GIFT")] == ["commission/gift.webp"]
    assert sorted(e.rel_path for e in gallery.find_by_name("main")) == [
        "ref/main-2024.png", "ref/main.png",
    ]
    assert gallery.find_by_name("不存在") == []


def test_set_meta_writes_manifest_and_reindexes(gallery):
    entry = gallery.set_meta(
        "commission/gift.webp", title="生贺", artist="SomeWolf", rating="nsfw",
        tags="anthro, 全身",
    )
    assert (entry.title, entry.artist, entry.rating) == ("生贺", "SomeWolf", "nsfw")
    assert entry.tags == ("anthro", "全身")
    saved = json.loads(gallery.manifest_path.read_text("utf-8"))
    assert saved["images"]["commission/gift.webp"]["rating"] == "nsfw"
    # 二次修改只动指定字段，其他保留
    entry = gallery.set_meta("commission/gift.webp", rating="safe")
    assert entry.rating == "safe" and entry.title == "生贺"


def test_set_meta_rejects_bad_input(gallery):
    with pytest.raises(GalleryError):
        gallery.set_meta("ref/main.png", rating="explicit")
    with pytest.raises(GalleryError):
        gallery.set_meta("ref/main.png", nickname="不支持的字段")
    with pytest.raises(GalleryError):
        gallery.set_meta("ref/不存在.png", title="x")
