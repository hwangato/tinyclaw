"""
Web 工具模块
============
提供 web_fetch（抓取网页）和 web_search（搜索引擎）两个工具。
使用 httpx 作为 HTTP 客户端。
"""

import json
from typing import TYPE_CHECKING

from tinyclaw.agent.compaction import micro_compact
from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from tinyclaw.config import WebConfig


def register_web_tools(registry: ToolRegistry, web_config: "WebConfig") -> None:
    """
    注册 Web 相关工具。

    参数:
        registry: 工具注册表
        web_config: Web 工具配置
    """

    @registry.tool("web_fetch", "抓取指定 URL 的网页内容（纯文本）。", {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的 URL"},
            "max_length": {
                "type": "integer",
                "default": 8192,
                "description": "最大返回字符数",
            },
        },
        "required": ["url"],
    })
    def web_fetch(url: str, max_length: int = 8192) -> str:
        """抓取网页内容并提取纯文本。"""
        try:
            import httpx
        except ImportError:
            return "web_fetch 需要安装 httpx: pip install httpx"

        try:
            with httpx.Client(timeout=web_config.fetch_timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={
                    "User-Agent": "TinyClaw/0.12 (AI Assistant Web Fetcher)",
                })
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "text/html" in content_type:
                    # 尝试用简易方式提取文本
                    text = _extract_text_from_html(resp.text)
                elif "application/json" in content_type:
                    text = json.dumps(resp.json(), ensure_ascii=False, indent=2)
                else:
                    text = resp.text

                max_len = min(max_length, web_config.max_content_length)
                return micro_compact(text, max_len) if text else "(空内容)"

        except Exception as e:
            return f"网页抓取失败: {e}"

    @registry.tool("web_search", "通过搜索引擎搜索信息。", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "num_results": {
                "type": "integer",
                "default": 5,
                "description": "返回结果数量",
            },
        },
        "required": ["query"],
    })
    def web_search(query: str, num_results: int = 5) -> str:
        """执行网络搜索。"""
        api = web_config.search_api.lower()
        if not api:
            return "未配置搜索 API。请在 config.yaml 中设置 web.search_api"

        if api == "searxng":
            return _search_searxng(query, num_results, web_config)
        elif api == "google":
            return _search_google(query, num_results, web_config)
        elif api == "bing":
            return _search_bing(query, num_results, web_config)
        else:
            return f"不支持的搜索 API: {api}（支持: google, bing, searxng）"


def _extract_text_from_html(html: str) -> str:
    """从 HTML 中提取纯文本（简易实现）。"""
    import re
    # 移除 script 和 style 标签
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # 移除所有 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)
    # 清理空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _search_searxng(query: str, num_results: int, web_config) -> str:
    """通过 SearXNG 实例搜索。"""
    try:
        import httpx
    except ImportError:
        return "web_search 需要安装 httpx: pip install httpx"

    if not web_config.search_api_url:
        return "未配置 SearXNG URL。请设置 web.search_api_url"

    try:
        url = f"{web_config.search_api_url.rstrip('/')}/search"
        with httpx.Client(timeout=web_config.fetch_timeout) as client:
            resp = client.get(url, params={
                "q": query,
                "format": "json",
                "number_of_results": num_results,
            })
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])[:num_results]
            if not results:
                return f"未找到与 '{query}' 相关的结果"
            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', '(无标题)')}")
                lines.append(f"   URL: {r.get('url', '')}")
                lines.append(f"   {r.get('content', '')[:200]}")
                lines.append("")
            return "\n".join(lines)
    except Exception as e:
        return f"SearXNG 搜索失败: {e}"


def _search_google(query: str, num_results: int, web_config) -> str:
    """通过 Google Custom Search API 搜索。"""
    try:
        import httpx
    except ImportError:
        return "web_search 需要安装 httpx: pip install httpx"

    if not web_config.search_api_key:
        return "未配置 Google API Key。请设置 web.search_api_key"

    try:
        with httpx.Client(timeout=web_config.fetch_timeout) as client:
            resp = client.get("https://www.googleapis.com/customsearch/v1", params={
                "key": web_config.search_api_key,
                "cx": web_config.search_api_url,  # Custom Search Engine ID
                "q": query,
                "num": min(num_results, 10),
            })
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return f"未找到与 '{query}' 相关的结果"
            lines = []
            for i, item in enumerate(items, 1):
                lines.append(f"{i}. {item.get('title', '(无标题)')}")
                lines.append(f"   URL: {item.get('link', '')}")
                lines.append(f"   {item.get('snippet', '')[:200]}")
                lines.append("")
            return "\n".join(lines)
    except Exception as e:
        return f"Google 搜索失败: {e}"


def _search_bing(query: str, num_results: int, web_config) -> str:
    """通过 Bing Search API 搜索。"""
    try:
        import httpx
    except ImportError:
        return "web_search 需要安装 httpx: pip install httpx"

    if not web_config.search_api_key:
        return "未配置 Bing API Key。请设置 web.search_api_key"

    try:
        with httpx.Client(timeout=web_config.fetch_timeout) as client:
            resp = client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                params={"q": query, "count": min(num_results, 50)},
                headers={"Ocp-Apim-Subscription-Key": web_config.search_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("webPages", {}).get("value", [])
            if not pages:
                return f"未找到与 '{query}' 相关的结果"
            lines = []
            for i, page in enumerate(pages[:num_results], 1):
                lines.append(f"{i}. {page.get('name', '(无标题)')}")
                lines.append(f"   URL: {page.get('url', '')}")
                lines.append(f"   {page.get('snippet', '')[:200]}")
                lines.append("")
            return "\n".join(lines)
    except Exception as e:
        return f"Bing 搜索失败: {e}"
