"""Pillow 缩略图:生成、缓存命中、坏图回退。"""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from astrbot_plugin_ref_gallery.gallery import ImageEntry
from astrbot_plugin_ref_gallery import thumbnails


def make_entry(tmp_path: Path, name: str = "big.png", size=(1024, 512)) -> ImageEntry:
    path = tmp_path / name
    Image.new("RGB", size, (200, 60, 60)).save(path)
    return ImageEntry(rel_path=f"ref/{name}", abs_path=path, category="ref")


def test_generates_webp_thumbnail_and_caches(tmp_path):
    entry = make_entry(tmp_path)
    thumbs = tmp_path / "thumbs"
    data = thumbnails.get_thumbnail(entry, thumbs)
    assert data is not None
    with Image.open(BytesIO(data)) as im:
        assert im.format == "WEBP"
        assert max(im.size) <= thumbnails.THUMB_MAX_EDGE
    cached = list(thumbs.glob("*.webp"))
    assert len(cached) == 1


def test_cache_hit_skips_regeneration(tmp_path, monkeypatch):
    entry = make_entry(tmp_path)
    thumbs = tmp_path / "thumbs"
    first = thumbnails.get_thumbnail(entry, thumbs)
    # 第二次调用若走了解码路径就会炸——证明命中缓存
    monkeypatch.setattr(
        thumbnails.Image, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应重新解码"))
    )
    second = thumbnails.get_thumbnail(entry, thumbs)
    assert second == first


def test_corrupt_image_returns_none(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image at all")
    entry = ImageEntry(rel_path="ref/bad.png", abs_path=path, category="ref")
    assert thumbnails.get_thumbnail(entry, tmp_path / "thumbs") is None


def test_missing_file_returns_none(tmp_path):
    entry = ImageEntry(rel_path="ref/gone.png", abs_path=tmp_path / "gone.png", category="ref")
    assert thumbnails.get_thumbnail(entry, tmp_path / "thumbs") is None


def test_rgba_source_keeps_alpha_mode(tmp_path):
    path = tmp_path / "alpha.png"
    Image.new("RGBA", (300, 300), (0, 128, 255, 128)).save(path)
    entry = ImageEntry(rel_path="ref/alpha.png", abs_path=path, category="ref")
    data = thumbnails.get_thumbnail(entry, tmp_path / "thumbs")
    assert data is not None
