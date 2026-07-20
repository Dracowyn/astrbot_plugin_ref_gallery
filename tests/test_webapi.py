"""webapi 逻辑函数直测(不经 HTTP 层)。"""

import json

import pytest
from PIL import Image

from astrbot_plugin_ref_gallery import webapi
from astrbot_plugin_ref_gallery.gallery import GalleryError
from test_main_draw import make_plugin


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "commission").mkdir()
    Image.new("RGB", (600, 400), (10, 120, 90)).save(root / "ref" / "main.png")
    (root / "commission" / "bad.webp").write_bytes(b"broken")
    (root / "manifest.json").write_text(
        json.dumps(
            {"images": {"commission/bad.webp": {"rating": "nsfw", "artist": "W"}}},
            ensure_ascii=False,
        ),
        "utf-8",
    )
    p = make_plugin(tmp_path)
    p.thumbs_dir = tmp_path / "thumbs"
    p.gallery.scan()
    return p


def test_overview_data_structure(plugin):
    data = webapi.overview_data(plugin)
    assert data["total"] == 2
    assert data["categories"] == {"ref": 1, "commission": 1}
    assert data["category_dirs"] == ["commission", "ref"]  # 含空目录、升序
    assert data["nsfw_count"] == 1
    assert data["coverage_pct"] == 50
    assert data["degraded"] is False
    assert data["nsfw_sessions"] == []


def test_list_images_filters_and_thumbs(plugin):
    data = webapi.list_images_data(plugin, "", "", "all", 1, 40)
    assert data["total"] == 2
    by_path = {i["rel_path"]: i for i in data["items"]}
    assert by_path["ref/main.png"]["thumb"].startswith("data:image/webp;base64,")
    assert by_path["commission/bad.webp"]["thumb"] is None  # 坏图回退 null

    assert webapi.list_images_data(plugin, "ref", "", "all", 1, 40)["total"] == 1
    assert webapi.list_images_data(plugin, "", "", "nsfw", 1, 40)["total"] == 1
    assert webapi.list_images_data(plugin, "", "W", "all", 1, 40)["total"] == 1  # 画师关键词
    assert webapi.list_images_data(plugin, "", "没有的词", "all", 1, 40)["total"] == 0


def test_list_images_pagination(plugin):
    data = webapi.list_images_data(plugin, "", "", "all", 1, 1)
    assert data["total"] == 2 and len(data["items"]) == 1 and data["page"] == 1
    page2 = webapi.list_images_data(plugin, "", "", "all", 2, 1)
    assert len(page2["items"]) == 1
    assert page2["items"][0]["rel_path"] != data["items"][0]["rel_path"]
    # page_size 超上限被钳制
    assert webapi.list_images_data(plugin, "", "", "all", 1, 999)["page_size"] == webapi.PAGE_SIZE_MAX


def test_image_detail_data(plugin):
    data = webapi.image_detail_data(plugin, "ref/main.png")
    assert data["data_uri"].startswith("data:image/png;base64,")
    assert data["size_bytes"] > 0
    with pytest.raises(GalleryError):
        webapi.image_detail_data(plugin, "ref/nope.png")


def test_delete_and_meta_delegate(plugin):
    updated = webapi.update_meta_data(plugin, "ref/main.png", {"title": "主设定"})
    assert updated["title"] == "主设定"
    result = webapi.delete_image_data(plugin, "commission/bad.webp")
    assert result == {"removed": "commission/bad.webp", "total": 1}
