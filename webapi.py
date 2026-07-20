"""图库管理页后端 Web API(经 register_web_api 注册,页面 bridge 调用)。

统一信封 {status, message, data}:bridge 对非 error 解出 data。
全部走仪表盘 JWT 鉴权(/api/v1/plugins/extensions/**),仅登录管理员可访问。

handle_* 只做请求解析(astrbot.api.web 的 request 代理)与信封包装;
*_data 逻辑函数接 (plugin, 已解析参数),可直接单测。磁盘密集操作走 asyncio.to_thread。
"""

import asyncio
import base64
import mimetypes
from typing import TYPE_CHECKING, Any

from astrbot.api.web import error_response, json_response, request

from .gallery import Gallery, GalleryError, ImageEntry
from .thumbnails import get_thumbnail

if TYPE_CHECKING:
    from .main import RefGalleryPlugin

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
PAGE_SIZE_DEFAULT = 40
PAGE_SIZE_MAX = 100


def _ok(data: Any = None):
    return json_response(
        {"status": "ok", "data": {} if data is None else data, "message": None}
    )


def _entry_dict(e: ImageEntry) -> dict:
    return {
        "rel_path": e.rel_path,
        "category": e.category,
        "title": e.title,
        "artist": e.artist,
        "tags": list(e.tags),
        "rating": e.rating,
    }


# ------------------------------ 概览 ------------------------------
def overview_data(plugin: "RefGalleryPlugin") -> dict:
    entries = plugin.gallery.entries
    with_meta = sum(1 for e in entries if e.title or e.artist or e.tags)
    return {
        "total": len(entries),
        "categories": plugin.gallery.categories(),
        "category_dirs": plugin.gallery.category_dirs(),
        "nsfw_count": sum(1 for e in entries if e.rating == "nsfw"),
        "coverage_pct": round(with_meta * 100 / len(entries)) if entries else 0,
        "degraded": plugin.gallery.manifest_degraded,
        "nsfw_sessions": list(plugin.config.get("nsfw_enabled_sessions", []) or []),
    }


async def handle_overview(plugin: "RefGalleryPlugin"):
    return _ok(overview_data(plugin))


# ------------------------------ 列表 / 详情 ------------------------------
def list_images_data(
    plugin: "RefGalleryPlugin",
    category: str,
    keyword: str,
    rating: str,
    page: int,
    page_size: int,
) -> dict:
    entries = [
        e
        for e in plugin.gallery.entries
        if Gallery._match(e, category, keyword, allow_nsfw=True)
        and (rating in ("", "all") or e.rating == rating)
    ]
    total = len(entries)
    page = max(1, page)
    page_size = min(max(1, page_size), PAGE_SIZE_MAX)
    start = (page - 1) * page_size
    items = []
    for e in entries[start : start + page_size]:
        thumb = get_thumbnail(e, plugin.thumbs_dir)
        items.append(
            {
                **_entry_dict(e),
                "thumb": (
                    f"data:image/webp;base64,{base64.b64encode(thumb).decode()}"
                    if thumb
                    else None
                ),
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def handle_images(plugin: "RefGalleryPlugin"):
    q = request.query
    data = await asyncio.to_thread(
        list_images_data,
        plugin,
        (q.get("category", "") or "").strip(),
        (q.get("keyword", "") or "").strip(),
        (q.get("rating", "all") or "all").strip(),
        q.get("page", 1, int) or 1,
        q.get("page_size", PAGE_SIZE_DEFAULT, int) or PAGE_SIZE_DEFAULT,
    )
    return _ok(data)


def image_detail_data(plugin: "RefGalleryPlugin", rel_path: str) -> dict:
    entry = next((e for e in plugin.gallery.entries if e.rel_path == rel_path), None)
    if entry is None:
        raise GalleryError(f"图库里没有 {rel_path}")
    data = entry.abs_path.read_bytes()
    mime = mimetypes.guess_type(entry.abs_path.name)[0] or "application/octet-stream"
    return {
        **_entry_dict(entry),
        "size_bytes": len(data),
        "data_uri": f"data:{mime};base64,{base64.b64encode(data).decode()}",
    }


async def handle_image(plugin: "RefGalleryPlugin"):
    rel_path = (request.query.get("path", "") or "").strip()
    try:
        data = await asyncio.to_thread(image_detail_data, plugin, rel_path)
    except (GalleryError, OSError) as e:
        return error_response(str(e), status_code=404)
    return _ok(data)


# ------------------------------ 上传 / 删除 / 元数据 ------------------------------
async def handle_upload(plugin: "RefGalleryPlugin", category: str):
    files = await request.files()
    file = files.get("file")
    if file is None:
        return error_response("缺少上传文件", status_code=400)
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        return error_response(
            f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限", status_code=413
        )
    try:
        entry = await asyncio.to_thread(
            plugin.gallery.add_image, category, file.filename or "", payload
        )
    except GalleryError as e:
        return error_response(str(e), status_code=400)
    return _ok({"rel_path": entry.rel_path})


def delete_image_data(plugin: "RefGalleryPlugin", rel_path: str) -> dict:
    plugin.gallery.remove(rel_path)
    return {"removed": rel_path, "total": len(plugin.gallery.entries)}


async def handle_delete(plugin: "RefGalleryPlugin"):
    body = await request.json({}) or {}
    rel_path = str(body.get("path", "") or "").strip()
    try:
        data = await asyncio.to_thread(delete_image_data, plugin, rel_path)
    except GalleryError as e:
        return error_response(str(e), status_code=404)
    return _ok(data)


def update_meta_data(plugin: "RefGalleryPlugin", rel_path: str, fields: dict) -> dict:
    return _entry_dict(plugin.gallery.set_meta(rel_path, **fields))


async def handle_meta(plugin: "RefGalleryPlugin"):
    body = await request.json({}) or {}
    rel_path = str(body.get("path", "") or "").strip()
    fields = {k: body[k] for k in ("title", "artist", "rating", "tags") if k in body}
    if not fields:
        return error_response("没有要更新的字段", status_code=400)
    try:
        data = await asyncio.to_thread(update_meta_data, plugin, rel_path, fields)
    except GalleryError as e:
        return error_response(str(e), status_code=400)
    return _ok(data)


# ------------------------------ 维护 ------------------------------
async def handle_rescan(plugin: "RefGalleryPlugin"):
    added, removed = await asyncio.to_thread(plugin.gallery.scan)
    return _ok(
        {"added": added, "removed": removed, "total": len(plugin.gallery.entries)}
    )


async def handle_nsfw_remove(plugin: "RefGalleryPlugin"):
    body = await request.json({}) or {}
    umo = str(body.get("umo", "") or "").strip()
    if not umo:
        return error_response("缺少 umo", status_code=400)
    plugin._set_nsfw(umo, False)
    return _ok(
        {"nsfw_sessions": list(plugin.config.get("nsfw_enabled_sessions", []) or [])}
    )
