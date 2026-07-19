"""LLM 工具 show_my_image + nsfw 会话开关。"""

import asyncio

import pytest

from test_main_draw import FakeEvent, make_plugin


class FakeContext:
    def __init__(self):
        self.sent: list[tuple[str, object]] = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "gallery"
    (root / "ref").mkdir(parents=True)
    (root / "ref" / "main.png").write_bytes(b"a")
    p = make_plugin(tmp_path, {"cooldown_seconds": 30})
    p.context = FakeContext()
    p.gallery.scan()
    return p


def test_llm_tool_sends_image_and_reports(plugin):
    reply = asyncio.run(plugin.llm_show_image(FakeEvent(), category="设定图"))
    assert len(plugin.context.sent) == 1
    assert "设定图" in reply and "main.png" in reply


def test_llm_tool_respects_cooldown(plugin):
    ev = FakeEvent()
    asyncio.run(plugin.llm_show_image(ev, category="ref"))
    reply = asyncio.run(plugin.llm_show_image(ev, category="ref"))
    assert len(plugin.context.sent) == 1
    assert "频繁" in reply


def test_llm_tool_disabled_by_config(plugin):
    plugin.config["llm_tool_enabled"] = False
    reply = asyncio.run(plugin.llm_show_image(FakeEvent()))
    assert plugin.context.sent == []
    assert "未启用" in reply


def test_llm_tool_empty_category_reports_miss(plugin):
    reply = asyncio.run(plugin.llm_show_image(FakeEvent(), category="commission"))
    assert plugin.context.sent == []
    assert "还没有图" in reply


def test_set_nsfw_toggles_whitelist_and_saves(plugin):
    umo = "aiocqhttp:GroupMessage:7"
    msg_on = plugin._set_nsfw(umo, True)
    assert plugin._nsfw_allowed(umo) is True
    assert plugin.config.saved == 1
    assert "允许" in msg_on
    # 重复开幂等
    plugin._set_nsfw(umo, True)
    assert plugin.config.get("nsfw_enabled_sessions").count(umo) == 1
    msg_off = plugin._set_nsfw(umo, False)
    assert plugin._nsfw_allowed(umo) is False
    assert "关闭" in msg_off
