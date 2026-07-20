"""Pillow 缩略图生成与磁盘缓存。

缓存 key 含原图 mtime_ns 与 size:原图变更后 key 变化,旧缓存自然失效(不主动清理,体积小)。
Pillow 是 AstrBot 宿主核心依赖(pyproject: pillow>=11.2.1),插件不新增依赖。
"""

import hashlib
import logging
import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image

from .gallery import ImageEntry

_log = logging.getLogger(__name__)

THUMB_MAX_EDGE = 256
THUMB_WEBP_QUALITY = 80


def _cache_key(entry: ImageEntry) -> str:
    stat = entry.abs_path.stat()
    raw = f"{entry.rel_path}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_thumbnail(entry: ImageEntry, thumbs_dir: Path) -> bytes | None:
    """返回 WebP 缩略图字节;命中缓存直接读;损坏/不可解码/文件缺失返回 None。"""
    try:
        key = _cache_key(entry)
    except OSError as e:
        _log.debug("Failed to stat source image %s: %s", entry.abs_path, e)
        return None
    cache_path = thumbs_dir / f"{key}.webp"
    if cache_path.is_file():
        try:
            return cache_path.read_bytes()
        except OSError as e:
            _log.debug("Failed to read thumbnail cache %s: %s", cache_path, e)
            pass
    try:
        with Image.open(entry.abs_path) as im:
            im.seek(0)  # 动图(GIF)取首帧
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            im.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
            buf = BytesIO()
            im.save(buf, format="WEBP", quality=THUMB_WEBP_QUALITY)
    except Exception as e:
        _log.debug("Failed to generate thumbnail for %s: %s", entry.abs_path, e)
        return None
    data = buf.getvalue()
    try:
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + rename to prevent partial writes under concurrent load
        with NamedTemporaryFile(dir=thumbs_dir, delete=False, suffix=".webp") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        os.replace(tmp_path, cache_path)
    except OSError as e:
        _log.debug("Failed to write thumbnail cache %s: %s", cache_path, e)
        pass  # 缓存写失败不影响本次返回
    return data
