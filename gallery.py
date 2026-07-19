"""图库核心：目录扫描、manifest.json 合并、筛选抽取、元数据写回。

纯逻辑模块，零 AstrBot 框架依赖，可直接单测。
索引主键是图片相对 gallery 根目录的 posix 路径（如 "ref/main.png"）。
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
RATINGS = ("safe", "nsfw")
MANIFEST_NAME = "manifest.json"


class GalleryError(Exception):
    """图库操作错误，message 面向用户可读。"""


@dataclass(frozen=True)
class ImageEntry:
    rel_path: str
    abs_path: Path
    category: str
    title: str = ""
    artist: str = ""
    tags: tuple[str, ...] = ()
    rating: str = "safe"


class Gallery:
    """内存索引 + JSON 清单。清单是可选增强：没有条目的图按目录类别 + safe 兜底。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / MANIFEST_NAME
        self.manifest_degraded = False
        self._entries: list[ImageEntry] = []

    # ------------------------------ 扫描 ------------------------------
    def scan(self) -> tuple[int, int]:
        """重扫目录 + 重读清单，重建索引。返回相对上次索引的 (新增数, 移除数)。"""
        old = {e.rel_path for e in self._entries}
        meta = self._load_manifest()
        entries: list[ImageEntry] = []
        if self.root.is_dir():
            for cat_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
                for f in sorted(cat_dir.rglob("*")):
                    if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
                        continue
                    rel = f.relative_to(self.root).as_posix()
                    entries.append(self._build_entry(rel, f, cat_dir.name, meta.get(rel, {})))
        self._entries = entries
        new = {e.rel_path for e in entries}
        return len(new - old), len(old - new)

    @staticmethod
    def _build_entry(rel: str, abs_path: Path, category: str, m: dict) -> ImageEntry:
        """单张图的清单条目合并；脏值（未知 rating、非列表 tags）静默回落默认。"""
        rating = str(m.get("rating", "safe")).lower()
        if rating not in RATINGS:
            rating = "safe"
        tags = m.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return ImageEntry(
            rel_path=rel,
            abs_path=abs_path,
            category=category,
            title=str(m.get("title", "") or ""),
            artist=str(m.get("artist", "") or ""),
            tags=tuple(str(t) for t in tags),
            rating=rating,
        )

    def _load_manifest(self) -> dict:
        """读清单的 images 映射；文件不存在返回 {}；损坏则置 degraded 并降级为纯目录模式。"""
        self.manifest_degraded = False
        if not self.manifest_path.is_file():
            return {}
        try:
            data = json.loads(self.manifest_path.read_text("utf-8"))
            images = data.get("images", {})
            if not isinstance(images, dict):
                raise ValueError("images 字段不是对象")
            return images
        except (ValueError, OSError):
            self.manifest_degraded = True
            return {}

    # ------------------------------ 查询 ------------------------------
    @property
    def entries(self) -> tuple[ImageEntry, ...]:
        return tuple(self._entries)

    def categories(self) -> dict[str, int]:
        """各类别图片数（只含非空类别）。"""
        out: dict[str, int] = {}
        for e in self._entries:
            out[e.category] = out.get(e.category, 0) + 1
        return out

    # ------------------------------ 抽取 ------------------------------
    def pick(
        self,
        category: str = "",
        keyword: str = "",
        allow_nsfw: bool = False,
        exclude: frozenset[str] | set[str] = frozenset(),
    ) -> ImageEntry | None:
        """筛选后随机抽一张；候选全在 exclude 里时忽略 exclude（重置防重复）。"""
        pool = [e for e in self._entries if self._match(e, category, keyword, allow_nsfw)]
        if not pool:
            return None
        fresh = [e for e in pool if e.rel_path not in exclude]
        return random.choice(fresh or pool)

    @staticmethod
    def _match(e: ImageEntry, category: str, keyword: str, allow_nsfw: bool) -> bool:
        if category and e.category != category:
            return False
        if e.rating == "nsfw" and not allow_nsfw:
            return False
        if keyword:
            kw = keyword.lower()
            hay = (
                e.title.lower(),
                e.artist.lower(),
                Path(e.rel_path).name.lower(),
                *(t.lower() for t in e.tags),
            )
            if not any(kw in h for h in hay):
                return False
        return True

    # ------------------------------ 查找 / 写回 ------------------------------
    def find_by_name(self, name: str) -> list[ImageEntry]:
        """按名字找图：先精确匹配相对路径；无命中再按文件名子串（不区分大小写）。"""
        name = name.strip()
        exact = [e for e in self._entries if e.rel_path == name]
        if exact:
            return exact
        low = name.lower()
        return [e for e in self._entries if low in Path(e.rel_path).name.lower()]

    def set_meta(self, rel_path: str, **fields) -> ImageEntry:
        """更新某图元数据并写回 manifest.json，随后重扫索引并返回新条目。

        允许字段：title / artist / rating / tags。tags 可传逗号分隔字符串。
        清单本身损坏时从空清单重建（degraded 状态下写回不吞异常）。
        """
        if rel_path not in {e.rel_path for e in self._entries}:
            raise GalleryError(f"图库里没有 {rel_path}")
        allowed = {"title", "artist", "rating", "tags"}
        bad = set(fields) - allowed
        if bad:
            raise GalleryError(f"不支持的字段：{'、'.join(sorted(bad))}（可用：title/artist/rating/tags）")
        if "rating" in fields and str(fields["rating"]).lower() not in RATINGS:
            raise GalleryError("rating 只能是 safe 或 nsfw")
        if "tags" in fields and isinstance(fields["tags"], str):
            fields["tags"] = [t.strip() for t in fields["tags"].split(",") if t.strip()]

        images = self._load_manifest()
        item = dict(images.get(rel_path, {}))
        item.update(fields)
        images[rel_path] = item
        self.manifest_path.write_text(
            json.dumps({"images": images}, ensure_ascii=False, indent=2) + "\n",
            "utf-8",
        )
        self.scan()
        for e in self._entries:
            if e.rel_path == rel_path:
                return e
        raise GalleryError(f"{rel_path} 在重扫后消失了，请检查图库目录")


def build_caption(entry: ImageEntry) -> str:
    """发图附言：「标题」 by 画师；缺哪个省哪个，都没有返回空串。"""
    parts = []
    if entry.title:
        parts.append(f"「{entry.title}」")
    if entry.artist:
        parts.append(f"by {entry.artist}")
    return " ".join(parts)
