"""管理页面静态约束:bridge 显式引用、加载顺序、无外部资源。"""

from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "pages" / "gallery" / "index.html"


def test_bridge_sdk_included_before_inline_script():
    """页面必须显式引用 bridge-sdk.js,且在内联脚本之前。

    服务端(plugin_page_service)只在页面未引用 bridge-sdk.js 时才自动注入,
    且注入点在 </body> 前——排在内联脚本之后,导致脚本执行时
    window.AstrBotPluginPage 尚未定义(v0.2.0 真机验收踩到的坑)。
    """
    html = PAGE.read_text("utf-8")
    bridge_pos = html.find('src="/api/plugin/page/bridge-sdk.js"')
    inline_pos = html.find("<script>")
    assert bridge_pos != -1, "缺少对 /api/plugin/page/bridge-sdk.js 的显式引用"
    assert inline_pos != -1
    assert bridge_pos < inline_pos, "bridge-sdk.js 必须在内联脚本之前加载"


def test_no_external_urls():
    html = PAGE.read_text("utf-8")
    assert "http://" not in html and "https://" not in html


def test_no_native_modal_dialogs():
    """页面不得调用原生阻塞弹窗(confirm/alert/prompt)。

    插件页面 iframe 的 sandbox 为 allow-scripts allow-forms allow-downloads,
    不含 allow-modals——原生弹窗会被浏览器静默忽略(confirm 恒返回 false),
    删除确认等流程会永远走不通(v0.2.0 真机验收踩到的坑)。
    """
    import re

    html = PAGE.read_text("utf-8")
    hits = re.findall(r"\b(?:window\s*\.\s*)?(?:confirm|alert|prompt)\s*\(", html)
    assert not hits, f"发现原生弹窗调用:{hits!r},请改用页面内确认交互"


def test_no_dynamic_src_href_literals_for_asset_rewriter():
    """页面源码里的 src=/href= 字面量只允许静态的 bridge-sdk 引用。

    服务端发页面时会用 _HTML_ASSET_ATTR_RE 重写整个 HTML 文本里的
    src/href 属性——包括内联 JS 模板字符串。动态值(如缩略图 data URI)
    必须用 DOM 属性赋值(el.src = ...)注入,否则模板占位符会在 serve 时
    被改写成废的资产 URL(v0.2.0 真机验收踩到的坑:缩略图全部破图)。
    """
    from astrbot.dashboard.services.plugin_page_service import _HTML_ASSET_ATTR_RE

    html = PAGE.read_text("utf-8")
    urls = [m.group("url") for m in _HTML_ASSET_ATTR_RE.finditer(html)]
    assert urls == ["/api/plugin/page/bridge-sdk.js"], (
        f"发现会被服务端资产重写误伤的 src/href 字面量:{urls!r}"
    )
