"""Gallery.pick 筛选抽取 + build_caption 署名。"""

import json

import pytest

from astrbot_plugin_ref_gallery.gallery import Gallery, ImageEntry, build_caption


@pytest.fixture
def gallery(tmp_path):
    root = tmp_path / "gallery"
    for cat in ("ref", "commission"):
        (root / cat).mkdir(parents=True)
    (root / "ref" / "main.png").write_bytes(b"a")
    (root / "ref" / "feral.jpg").write_bytes(b"b")
    (root / "commission" / "gift.webp").write_bytes(b"c")
    (root / "commission" / "secret.png").write_bytes(b"d")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "images": {
                    "ref/main.png": {"title": "主设定", "artist": "SomeWolf", "tags": ["anthro"]},
                    "commission/secret.png": {"rating": "nsfw"},
                }
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    g = Gallery(root)
    g.scan()
    return g


def test_pick_filters_by_category(gallery):
    for _ in range(20):
        e = gallery.pick(category="ref")
        assert e is not None and e.category == "ref"


def test_pick_excludes_nsfw_by_default(gallery):
    for _ in range(20):
        e = gallery.pick(category="commission")
        assert e is not None and e.rel_path == "commission/gift.webp"


def test_pick_allows_nsfw_when_enabled(gallery):
    seen = {gallery.pick(category="commission", allow_nsfw=True).rel_path for _ in range(50)}
    assert "commission/secret.png" in seen


def test_pick_keyword_matches_title_artist_tags_filename(gallery):
    assert gallery.pick(keyword="主设定").rel_path == "ref/main.png"
    assert gallery.pick(keyword="somewolf").rel_path == "ref/main.png"  # 大小写不敏感
    assert gallery.pick(keyword="anthro").rel_path == "ref/main.png"
    assert gallery.pick(keyword="feral").rel_path == "ref/feral.jpg"   # 文件名
    assert gallery.pick(keyword="不存在的词") is None


def test_pick_respects_exclude_and_resets_when_exhausted(gallery):
    e = gallery.pick(category="ref", exclude={"ref/main.png"})
    assert e.rel_path == "ref/feral.jpg"
    # 全部被排除时重置（允许重复），而不是返回 None
    e = gallery.pick(category="ref", exclude={"ref/main.png", "ref/feral.jpg"})
    assert e is not None


def test_pick_empty_pool_returns_none(gallery):
    assert gallery.pick(category="不存在的类别") is None


def test_build_caption_variants(tmp_path):
    def entry(title, artist):
        return ImageEntry(
            rel_path="ref/x.png", abs_path=tmp_path / "x.png",
            category="ref", title=title, artist=artist,
        )

    assert build_caption(entry("主设定", "SomeWolf")) == "「主设定」 by SomeWolf"
    assert build_caption(entry("主设定", "")) == "「主设定」"
    assert build_caption(entry("", "SomeWolf")) == "by SomeWolf"
    assert build_caption(entry("", "")) == ""
