"""astrbot_plugin_ref_gallery —— bot 人设图库。

被问「你的设定图 / 照片 / 约的稿子」时，从本地图库按类别挑一张图发送。
- 指令：`设定图 [关键词]`（别名 `来张设定`）、`约稿图 [关键词]`
- LLM 工具：`show_my_image`，机器人被唤醒时可自行调用发图（与指令共用冷却）
- 管理指令：重扫图库 / 图库状态 / 图库信息 / 图库标记 / 图库nsfw（见 Task 5/6）
"""

# 注意：本模块特意不使用 `from __future__ import annotations`。该 future 会把注解
# 字符串化（PEP 563），使 GreedyStr 注解变成字符串，破坏框架的贪婪参数分发。
import time
from collections import deque
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, llm_tool, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from .gallery import Gallery, build_caption

PLUGIN_NAME = "astrbot_plugin_ref_gallery"
BUILTIN_CATEGORIES = ("ref", "commission", "daily")
# 类别的中文名，用于提示文案与 LLM 工具返回值
CATEGORY_LABELS = {"ref": "设定图", "commission": "约稿", "daily": "日常照片"}
# 无配置（或配置为空）时的类别别名兜底，与 _conf_schema.json 的 default 保持一致
DEFAULT_ALIASES = {
    "ref": "设定图,设定,参考图,refsheet",
    "commission": "约稿,稿子,委托,commission",
    "daily": "日常,照片,自拍,daily",
}


class RefGalleryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context, config)
        self.config = config
        self.gallery = Gallery(StarTools.get_data_dir(PLUGIN_NAME) / "gallery")
        # 会话级冷却：unified_msg_origin -> 上次发图时间戳
        self._last_sent: dict[str, float] = {}
        # 会话级防重复：unified_msg_origin -> 最近发过的 rel_path
        self._recent: dict[str, deque] = {}

    # ------------------------------ 生命周期 ------------------------------
    async def initialize(self) -> None:
        for cat in BUILTIN_CATEGORIES:
            (self.gallery.root / cat).mkdir(parents=True, exist_ok=True)
        added, _ = self.gallery.scan()
        logger.info(f"[{PLUGIN_NAME}] initialized, {added} images indexed")

    async def terminate(self) -> None:
        logger.info(f"[{PLUGIN_NAME}] terminated")

    # ------------------------------ 抽图指令 ------------------------------
    @filter.command("设定图", alias={"来张设定"})
    async def draw_ref(self, event: AstrMessageEvent, keyword: GreedyStr):
        """设定图 [关键词]：从设定图库随机抽一张发送。"""
        async for r in self._draw(event, "ref", keyword):
            yield r

    @filter.command("约稿图")
    async def draw_commission(self, event: AstrMessageEvent, keyword: GreedyStr):
        """约稿图 [关键词]：从约稿库随机抽一张发送。"""
        async for r in self._draw(event, "commission", keyword):
            yield r

    async def _draw(self, event: AstrMessageEvent, category: str, keyword: str):
        """指令共用主体：开关 → 冷却 → 抽图 → 发送。"""
        if not self._cfg_bool("enabled", True):
            return
        umo = event.unified_msg_origin
        wait = self._acquire_cooldown(umo, time.time())
        if wait:
            yield event.plain_result(f"歇会儿~ {wait}s 后再来")
            return
        chain, note = self._pick_chain(umo, category, (keyword or "").strip())
        if chain is None:
            yield event.plain_result(note)
            return
        yield event.chain_result(chain)

    # ------------------------------ 抽图核心 ------------------------------
    def _pick_chain(self, umo: str, category: str, keyword: str):
        """抽一张图。成功返回 (消息链, 说明文字)；失败返回 (None, 用户可读提示)。

        说明文字 = 附言（有元数据时）或文件名，供 LLM 工具向模型描述发了什么。
        """
        allow_nsfw = self._nsfw_allowed(umo)
        recent = self._recent_deque(umo)
        entry = self.gallery.pick(
            category=category, keyword=keyword,
            allow_nsfw=allow_nsfw, exclude=set(recent),
        )
        if entry is not None and not entry.abs_path.is_file():
            # 索引后文件被人工移走：重扫一次再试
            logger.warning(f"[{PLUGIN_NAME}] {entry.rel_path} 不在磁盘上，触发重扫")
            self.gallery.scan()
            entry = self.gallery.pick(
                category=category, keyword=keyword,
                allow_nsfw=allow_nsfw, exclude=set(recent),
            )
        if entry is None:
            label = CATEGORY_LABELS.get(category, category)
            if keyword:
                return None, f"没找到和「{keyword}」相关的图，换个词试试？"
            return None, f"「{label}」分类还没有图，快去投喂~"

        recent.append(entry.rel_path)
        chain = [Comp.Image.fromFileSystem(str(entry.abs_path))]
        caption = build_caption(entry) if self._cfg_bool("show_caption", True) else ""
        if caption:
            chain.append(Comp.Plain(caption))
        return chain, caption or Path(entry.rel_path).name

    def _recent_deque(self, umo: str) -> deque:
        """取该会话的防重复队列；容量跟随配置，变更时保留已有记录重建。"""
        size = self._cfg_int("recent_history_size", 10, minimum=1)
        recent = self._recent.get(umo)
        if recent is None or recent.maxlen != size:
            recent = deque(recent or (), maxlen=size)
            self._recent[umo] = recent
        return recent

    # ------------------------------ 判定 helper ------------------------------
    def _resolve_category(self, word: str) -> str:
        """把用户 / LLM 给的类别词解析成目录名；解析不了回落 ref。"""
        word = (word or "").strip().lower()
        if not word:
            return "ref"
        if word in BUILTIN_CATEGORIES or word in self.gallery.categories():
            return word
        for cat in BUILTIN_CATEGORIES:
            aliases = str(self.config.get(f"{cat}_aliases", "") or DEFAULT_ALIASES[cat])
            if word in (a.strip().lower() for a in aliases.split(",") if a.strip()):
                return cat
        return "ref"

    def _nsfw_allowed(self, umo: str) -> bool:
        sessions = self.config.get("nsfw_enabled_sessions", []) or []
        return umo in sessions

    def _acquire_cooldown(self, umo: str, now: float) -> int:
        """尝试获取发图资格。返回 0 表示放行（并记账），>0 表示还需等待的秒数。"""
        cd = self._cfg_int("cooldown_seconds", 30, minimum=0)
        if cd <= 0:
            self._last_sent[umo] = now
            return 0
        remain = cd - (now - self._last_sent.get(umo, 0.0))
        if remain > 0:
            return max(1, int(remain))
        self._last_sent[umo] = now
        return 0

    # ------------------------------ 配置 helper ------------------------------
    def _cfg_int(self, key: str, default: int, *, minimum: int | None = None) -> int:
        """读取整数配置；脏值 / None 回落默认值，可选下限钳制。"""
        try:
            val = int(self.config.get(key, default))
        except (TypeError, ValueError):
            val = default
        if minimum is not None and val < minimum:
            return minimum
        return val

    def _cfg_bool(self, key: str, default: bool) -> bool:
        """读取布尔配置；字符串 'false'/'0'/'no'/'off'/'' 视为 False。"""
        val = self.config.get(key, default)
        if isinstance(val, str):
            return val.strip().lower() not in ("", "false", "0", "no", "off")
        return bool(val)

    # ------------------------------ LLM 工具 ------------------------------
    @llm_tool("show_my_image")
    async def llm_show_image(
        self, event: AstrMessageEvent, category: str = "ref", keyword: str = ""
    ):
        """把你（bot）自己的设定图 / 约稿 / 日常照片直接发到当前会话。
        当用户想看你的设定图、参考图、照片、约的稿子、立绘、人设时调用本工具。
        图片会由工具直接发出，你只需根据返回结果自然地回应用户。

        Args:
            category(string): 图片类别：ref=设定图（默认）、commission=约稿、daily=日常照片。也接受中文别名如「设定图」「约稿」「照片」。
            keyword(string): 可选筛选词，匹配标题 / 画师 / 标签 / 文件名。留空＝类别内随机。
        """
        if not self._cfg_bool("enabled", True) or not self._cfg_bool("llm_tool_enabled", True):
            return "发图功能当前未启用。"

        umo = event.unified_msg_origin
        # 与指令共用冷却：防止 LLM 被诱导高频调用刷屏
        wait = self._acquire_cooldown(umo, time.time())
        if wait:
            return f"发图过于频繁，请 {wait}s 后再试。"

        cat = self._resolve_category(category)
        chain, note = self._pick_chain(umo, cat, (keyword or "").strip())
        if chain is None:
            return note
        try:
            await self.context.send_message(umo, MessageChain(chain=chain))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] llm tool send failed: {e}")
            return "图片已选好但发送失败。"
        label = CATEGORY_LABELS.get(cat, cat)
        return f"已发送一张{label}：{note}。请自然地回应用户。"

    # ------------------------------ nsfw 开关 ------------------------------
    def _set_nsfw(self, umo: str, enable: bool) -> str:
        """把会话加入 / 移出 nsfw 白名单并持久化，返回回复文案。"""
        sessions = list(self.config.get("nsfw_enabled_sessions", []) or [])
        if enable:
            if umo not in sessions:
                sessions.append(umo)
        else:
            sessions = [s for s in sessions if s != umo]
        self.config["nsfw_enabled_sessions"] = sessions
        self.config.save_config()
        return "本会话已允许 nsfw 图~" if enable else "本会话已关闭 nsfw 图。"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("图库nsfw")
    async def nsfw_toggle(self, event: AstrMessageEvent, switch: str = ""):
        """图库nsfw on|off：允许 / 禁止本会话抽到 nsfw 图（管理员）。"""
        umo = event.unified_msg_origin
        switch = (switch or "").strip().lower()
        if switch in ("on", "off"):
            yield event.plain_result(self._set_nsfw(umo, switch == "on"))
        else:
            state = "开" if self._nsfw_allowed(umo) else "关"
            yield event.plain_result(f"用法：图库nsfw on|off（本会话当前：{state}）")
