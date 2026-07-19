"""管理指令的可测逻辑：状态汇总与标记解析。"""

import json

import pytest

from test_main_draw import make_plugin


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "commission").mkdir()
    (root / "ref" / "main.png").write_bytes(b"a")
    (root / "commission" / "gift.webp").write_bytes(b"b")
    (root / "manifest.json").write_text(
        json.dumps({"images": {"commission/gift.webp": {"rating": "nsfw", "artist": "W"}}}),
        "utf-8",
    )
    p = make_plugin(tmp_path)
    p.gallery.scan()
    return p


def test_status_lines_summary(plugin):
    text = "\n".join(plugin._status_lines("some:session:1"))
    assert "总数：2" in text
    assert "ref：1" in text and "commission：1" in text
    assert "nsfw：1" in text
    assert "清单覆盖率：50%" in text
    assert "本会话 nsfw：关" in text


def test_status_lines_degraded_warning(plugin):
    plugin.gallery.manifest_path.write_text("{broken", "utf-8")
    plugin.gallery.scan()
    text = "\n".join(plugin._status_lines("s"))
    assert "降级" in text


def test_apply_mark_updates_meta(plugin):
    reply = plugin._apply_mark("gift", "title=生贺")
    assert "commission/gift.webp" in reply
    e = plugin.gallery.find_by_name("commission/gift.webp")[0]
    assert e.title == "生贺" and e.artist == "W"  # 原字段保留


def test_apply_mark_errors(plugin):
    assert "没找到" in plugin._apply_mark("不存在", "title=x")
    assert "格式" in plugin._apply_mark("gift", "没有等号")
    assert "rating 只能是" in plugin._apply_mark("gift", "rating=explicit")
    # 多张命中：提示用完整路径重试并列出候选
    (plugin.gallery.root / "ref" / "gift2.png").write_bytes(b"c")
    plugin.gallery.scan()
    reply = plugin._apply_mark("gif", "title=x")
    assert "多张" in reply and "commission/gift.webp" in reply
