"""解析微信公众号文章链接，提取公众号标识信息"""

from urllib.parse import urlparse, parse_qs
import re


def is_short_url(url: str) -> bool:
    """判断是否为微信短链接（/s/xxxx 格式，没有 query 参数）"""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    # 短链接格式: /s/xxxx（路径有两段且无 __biz 参数）
    return (
        "mp.weixin.qq.com" in parsed.netloc
        and re.match(r"^/s/.+", path)
        and "__biz" not in (parsed.query or "")
    )


def parse_article_url(url: str) -> dict:
    """
    解析微信公众号文章 URL，提取关键参数。

    支持的 URL 格式：
    - https://mp.weixin.qq.com/s/xxxxx (短链接)
    - https://mp.weixin.qq.com/s?__biz=xxx&mid=xxx&idx=xxx&sn=xxx (完整链接)

    返回:
        dict: 包含 biz, mid, idx, sn 等参数
    """
    url = url.strip()

    parsed = urlparse(url)
    if "mp.weixin.qq.com" not in parsed.netloc:
        raise ValueError("不是有效的微信公众号文章链接，请输入 mp.weixin.qq.com 域名的链接")

    params = parse_qs(parsed.query)

    result = {
        "url": url,
        "is_short": is_short_url(url),
        "biz": _extract_param(params, "__biz"),
        "mid": _extract_param(params, "mid"),
        "idx": _extract_param(params, "idx"),
        "sn": _extract_param(params, "sn"),
    }

    return result


def _extract_param(params: dict, key: str) -> str | None:
    """从 query params 中提取单个值"""
    values = params.get(key)
    if values:
        return values[0]
    return None


def is_valid_wechat_url(url: str) -> bool:
    """检查是否为有效的微信公众号文章链接"""
    try:
        parsed = urlparse(url.strip())
        return "mp.weixin.qq.com" in parsed.netloc and "/s" in parsed.path
    except Exception:
        return False


def extract_biz_from_url(url: str) -> str | None:
    """从文章 URL 中提取 __biz 参数（公众号唯一标识）"""
    try:
        info = parse_article_url(url)
        return info.get("biz")
    except ValueError:
        return None


async def resolve_short_url(url: str) -> dict:
    """
    通过 Playwright 访问短链接，获取重定向后的完整 URL 并解析出 __biz。
    同时从页面中提取公众号名称。

    返回:
        dict: {"biz": ..., "nickname": ..., "full_url": ...}
    """
    from playwright.async_api import async_playwright

    result = {"biz": None, "nickname": None, "full_url": None}

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # 方法1：从重定向后的 URL 提取
        final_url = page.url
        result["full_url"] = final_url
        parsed = parse_article_url(final_url)
        if parsed.get("biz"):
            result["biz"] = parsed["biz"]

        # 方法2：从页面 JS 变量中提取 biz
        if not result["biz"]:
            biz = await page.evaluate("""
                () => {
                    // 微信文章页面会在 JS 中存储 biz
                    const html = document.documentElement.innerHTML;
                    const match = html.match(/var\\s+biz\\s*=\\s*["']([^"']+)["']/);
                    if (match) return match[1];
                    const match2 = html.match(/__biz[=:]\\s*["']?([A-Za-z0-9=]+)/);
                    if (match2) return match2[1];
                    return null;
                }
            """)
            if biz:
                result["biz"] = biz

        # 提取公众号名称
        try:
            nickname = await page.evaluate("""
                () => {
                    // 从页面元素中获取公众号名称
                    const el = document.getElementById('js_name')
                        || document.querySelector('.rich_media_meta_nickname .profile_nickname')
                        || document.querySelector('a.weui-wa-hotarea');
                    return el ? el.textContent.trim() : null;
                }
            """)
            if nickname:
                result["nickname"] = nickname
        except Exception:
            pass

    except Exception as e:
        print(f"解析短链接失败: {e}")
    finally:
        await browser.close()
        await p.stop()

    return result
