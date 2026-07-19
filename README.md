# astrbot_plugin_ref_gallery · 设定图库

bot 人设图库：被问「你的设定图 / 照片 / 约的稿子」时，从本地图库按类别挑一张发送。
面向龙圈 / furry 场景，图片带画师署名，支持 SFW/NSFW 分级与会话白名单。

## 安装

- WebUI：插件市场 → 从仓库地址安装，填 `https://github.com/Dracowyn/astrbot_plugin_ref_gallery`。
- 手动：克隆本仓库到 AstrBot 的 `data/plugins/` 下后重启。

无第三方依赖，要求 AstrBot >= 4.25。

## 图库目录

位于 `data/plugin_data/astrbot_plugin_ref_gallery/gallery/`（首次启动自动创建）：

```
gallery/
├─ manifest.json   # 可选元数据清单
├─ ref/            # 设定图
├─ commission/     # 约稿
└─ daily/          # 日常 / 照片
```

**加图 = 把图扔进对应目录**（png/jpg/jpeg/gif/webp），然后发 `重扫图库`（或重启）。
新建其他子目录即新增类别。

## manifest.json（可选）

给图片补标题 / 画师 / 标签 / 分级。没有条目的图默认：目录即类别、rating=safe。

```json
{
  "images": {
    "commission/by-somewolf.png": {
      "title": "2025 生贺稿",
      "artist": "SomeWolf",
      "tags": ["anthro", "全身"],
      "rating": "nsfw"
    }
  }
}
```

清单损坏时插件自动降级为纯目录模式（`图库状态` 里会有提示），不会崩。

## 触发方式

- **自然语言（主路径）**：唤醒 bot 后问「你的设定图呢」「看看你约的稿子」——LLM 调用
  `show_my_image` 工具挑图直发。
- **指令**：`设定图 [关键词]`（别名 `来张设定`）、`约稿图 [关键词]`。

关键词匹配标题 / 画师 / 标签 / 文件名。同会话冷却默认 30s，最近发过的 10 张不重复。

## 管理指令（管理员）

| 指令 | 说明 |
|---|---|
| `重扫图库` | 重新扫描目录与清单 |
| `图库状态` | 张数 / 分级 / 清单覆盖率 / 本会话 nsfw 开关 |
| `图库信息 <文件名>` | 查看某图元数据 |
| `图库标记 <文件名> <key>=<value>` | 改 title/artist/rating/tags（tags 逗号分隔） |
| `图库nsfw on\|off` | 本会话允许 / 禁止 nsfw 图（默认全局禁止） |

## 配置

见 WebUI 插件配置页：开关、冷却、署名、防重复条数、类别中文别名、nsfw 会话白名单。

## 开发

```bash
# 在 AstrBot 仓库根目录运行测试
python -m pytest data/plugins/astrbot_plugin_ref_gallery/tests -v
```

`gallery.py` 为零框架依赖的纯逻辑层，`main.py` 为插件层；测试不需要启动 bot。

## License

[MIT](LICENSE)
