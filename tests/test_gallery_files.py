"""Gallery.add_image 上传写盘 + Gallery.remove 删除清理。"""

import json

import pytest

from astrbot_plugin_ref_gallery.gallery import Gallery, GalleryError


@pytest.fixture
def gallery(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "commission").mkdir()
    (root / "ref" / "main.png").write_bytes(b"a")
    (root / "manifest.json").write_text(
        json.dumps({"images": {"ref/main.png": {"title": "主设定"}}}, ensure_ascii=False),
        "utf-8",
    )
    g = Gallery(root)
    g.scan()
    return g


def test_add_image_writes_and_indexes(gallery):
    entry = gallery.add_image("commission", "gift.png", b"data")
    assert entry.rel_path == "commission/gift.png"
    assert entry.category == "commission"
    assert (gallery.root / "commission" / "gift.png").read_bytes() == b"data"
    assert entry.rel_path in {e.rel_path for e in gallery.entries}


def test_add_image_dedupes_filename(gallery):
    first = gallery.add_image("ref", "main.png", b"b")
    assert first.rel_path == "ref/main-1.png"
    second = gallery.add_image("ref", "main.png", b"c")
    assert second.rel_path == "ref/main-2.png"


def test_add_image_sanitizes_traversal_filename(gallery):
    entry = gallery.add_image("ref", "../../evil.png", b"x")
    assert entry.rel_path == "ref/evil.png"
    assert (gallery.root / "ref" / "evil.png").is_file()
    assert not (gallery.root.parent / "evil.png").exists()


def test_add_image_rejects_bad_input(gallery):
    with pytest.raises(GalleryError):
        gallery.add_image("ref", "note.txt", b"x")          # 扩展名不合法
    with pytest.raises(GalleryError):
        gallery.add_image("不存在", "a.png", b"x")           # 类别不存在
    with pytest.raises(GalleryError):
        gallery.add_image("../ref", "a.png", b"x")           # 类别含路径分隔
    with pytest.raises(GalleryError):
        gallery.add_image("ref", "///", b"x")                # 净化后为空


def test_remove_deletes_file_manifest_and_index(gallery):
    gallery.remove("ref/main.png")
    assert not (gallery.root / "ref" / "main.png").exists()
    assert "ref/main.png" not in {e.rel_path for e in gallery.entries}
    saved = json.loads(gallery.manifest_path.read_text("utf-8"))
    assert "ref/main.png" not in saved["images"]


def test_remove_is_idempotent_when_file_already_gone(gallery):
    (gallery.root / "ref" / "main.png").unlink()  # 文件被人工删走,但仍在索引里
    gallery.remove("ref/main.png")                # 不应抛错,仍清理清单与索引
    assert "ref/main.png" not in {e.rel_path for e in gallery.entries}


def test_remove_unknown_path_raises(gallery):
    with pytest.raises(GalleryError):
        gallery.remove("ref/nope.png")
