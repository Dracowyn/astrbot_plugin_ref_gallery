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
    with Image.open(BytesIO(data)) as im:
        assert im.mode == "RGBA"


def test_cache_invalidation_on_mtime_change(tmp_path):
    """Cache key changes when source mtime changes, so old cache is skipped."""
    entry = make_entry(tmp_path, name="evolving.png", size=(500, 500))
    thumbs = tmp_path / "thumbs"
    first_data = thumbnails.get_thumbnail(entry, thumbs)

    # Modify the source to change mtime (or size), invalidating cache key
    import time
    time.sleep(0.01)  # Ensure mtime_ns differs
    # Write a new valid PNG file with different dimensions to change both mtime and size
    Image.new("RGB", (400, 400), (100, 200, 50)).save(entry.abs_path)

    # Cache key should be different now, so we regenerate
    second_data = thumbnails.get_thumbnail(entry, thumbs)
    # Both succeed but may differ due to different source dimensions
    assert first_data is not None
    assert second_data is not None
    # Verify two cache files exist (different keys)
    cached = list(thumbs.glob("*.webp"))
    assert len(cached) == 2


def test_gif_animation_takes_first_frame(tmp_path):
    """Verify GIF selects frame 0 (first frame) for thumbnail."""
    path = tmp_path / "animated.gif"
    # Create a 2-frame GIF: first frame red, second frame blue
    frames = [
        Image.new("RGB", (200, 200), (255, 0, 0)),  # Red frame 0
        Image.new("RGB", (200, 200), (0, 0, 255)),  # Blue frame 1
    ]
    frames[0].save(path, save_all=True, append_images=[frames[1]], duration=[100, 100])

    entry = ImageEntry(rel_path="ref/animated.gif", abs_path=path, category="ref")
    data = thumbnails.get_thumbnail(entry, tmp_path / "thumbs")
    assert data is not None

    # Check that we got the red frame (frame 0), not blue frame 1
    # Red and blue WebP should differ in their bytes
    # Decode to verify it's a real image and not corrupted
    with Image.open(BytesIO(data)) as im:
        assert im.format == "WEBP"
        # Sample a pixel to confirm it's reddish (from frame 0)
        pixel = im.getpixel((100, 100))
        # WebP may have slightly different colors after re-encoding, so check general hue
        # Red frame should have high R channel
        assert pixel[0] > pixel[2], "Should be reddish (frame 0), not blueish (frame 1)"
