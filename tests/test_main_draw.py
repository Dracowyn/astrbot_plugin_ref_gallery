"""指令层：抽图发送、冷却、类别解析、空库提示。

测试基建（FakeConfig / FakeEvent / drain / make_plugin）定义于此，
test_main_llm.py 与 test_main_admin.py 直接从本模块 import。
"""

import asyncio
from pathlib import Path

import pytest

import astrbot.api.message_components as Comp
from astrbot_plugin_ref_gallery.gallery import Gallery
from astrbot_plugin_ref_gallery.main import RefGalleryPlugin


class FakeConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self) -> None:
        self.saved += 1


class FakeEvent:
    def __init__(self, umo: str = "aiocqhttp:GroupMessage:1"):
        self.unified_msg_origin = umo

    def plain_result(self, text: str):
        return ("plain", text)

    def chain_result(self, chain: list):
        return ("chain", chain)


def drain(agen):
    """跑完一个 async 生成器处理器，收集全部 yield 结果。"""

    async def _collect():
        return [r async for r in agen]

    return asyncio.run(_collect())


def make_plugin(tmp_path: Path, config: dict | None = None) -> RefGalleryPlugin:
    """绕过 Star.__init__（需要框架 Context），手工装配插件实例。"""
    p = RefGalleryPlugin.__new__(RefGalleryPlugin)
    p.config = FakeConfig(config or {})
    p.gallery = Gallery(tmp_path / "gallery")
    p._last_sent = {}
    p._recent = {}
    return p


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "commission").mkdir()
    (root / "ref" / "main.png").write_bytes(b"a")
    p = make_plugin(tmp_path, {"cooldown_seconds": 30})
    p.gallery.scan()
    return p


def test_draw_sends_image_chain(plugin):
    results = drain(plugin._draw(FakeEvent(), "ref", ""))
    assert len(results) == 1
    kind, chain = results[0]
    assert kind == "chain"
    assert isinstance(chain[0], Comp.Image)


def test_draw_cooldown_blocks_second_call(plugin):
    ev = FakeEvent()
    drain(plugin._draw(ev, "ref", ""))
    results = drain(plugin._draw(ev, "ref", ""))
    assert results[0][0] == "plain" and "歇会儿" in results[0][1]


def test_draw_empty_category_friendly_message(plugin):
    results = drain(plugin._draw(FakeEvent(), "commission", ""))
    assert results[0][0] == "plain" and "还没有图" in results[0][1]


def test_draw_keyword_miss_message(plugin):
    results = drain(plugin._draw(FakeEvent(), "ref", "不存在的词"))
    assert results[0][0] == "plain" and "不存在的词" in results[0][1]


def test_draw_disabled_yields_nothing(plugin):
    plugin.config["enabled"] = False
    assert drain(plugin._draw(FakeEvent(), "ref", "")) == []


def test_pick_chain_caption_and_recent(plugin):
    umo = "aiocqhttp:GroupMessage:2"
    plugin.gallery.set_meta("ref/main.png", title="主设定", artist="SomeWolf")
    chain, note = plugin._pick_chain(umo, "ref", "")
    assert isinstance(chain[0], Comp.Image)
    assert isinstance(chain[1], Comp.Plain) and "SomeWolf" in chain[1].text
    assert note == "「主设定」 by SomeWolf"
    assert list(plugin._recent[umo]) == ["ref/main.png"]


def test_pick_chain_no_caption_when_disabled(plugin):
    plugin.config["show_caption"] = False
    plugin.gallery.set_meta("ref/main.png", title="主设定")
    chain, note = plugin._pick_chain("u", "ref", "")
    assert len(chain) == 1
    assert note == "main.png"  # 无附言时回退文件名，供 LLM 工具描述用


def test_pick_chain_deleted_file_rescans(plugin):
    (plugin.gallery.root / "ref" / "main.png").unlink()
    chain, note = plugin._pick_chain("u", "ref", "")
    assert chain is None and "还没有图" in note


def test_resolve_category_aliases(plugin):
    assert plugin._resolve_category("ref") == "ref"
    assert plugin._resolve_category("设定图") == "ref"
    assert plugin._resolve_category("约稿") == "commission"
    assert plugin._resolve_category("照片") == "daily"
    assert plugin._resolve_category("") == "ref"
    assert plugin._resolve_category("看不懂的词") == "ref"


def test_nsfw_allowed_reads_whitelist(plugin):
    umo = "aiocqhttp:GroupMessage:9"
    assert plugin._nsfw_allowed(umo) is False
    plugin.config["nsfw_enabled_sessions"] = [umo]
    assert plugin._nsfw_allowed(umo) is True
