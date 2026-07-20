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
