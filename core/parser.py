"""解析微信公众号文章链接，提取公众号标识信息"""

from urllib.parse import urlparse, parse_qs
import re

from config import WECHAT_MOBILE_UA, PROFILE_EXT_URL


def is_short_url(url: str) -> bool:
    """判断是否为微信短链接（/s/xxxx 格式，没有 query 参数）"""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return (
        "mp.weixin.qq.com" in parsed.netloc
        and bool(re.match(r"^/s/.+", path))
        and "__biz" not in (parsed.query or "")
    )


def parse_article_url(url: str) -> dict:
    """
    解析微信公众号文章 URL，提取关键参数。

    支持的 URL 格式：
    - https://mp.weixin.qq.com/s/xxxxx (短链接)
    - https://mp.weixin.qq.com/s?__biz=xxx&mid=xxx&idx=xxx&sn=xxx (完整链接)
    """
    url = url.strip()
    parsed = urlparse(url)
    if "mp.weixin.qq.com" not in parsed.netloc:
        raise ValueError("不是有效的微信公众号文章链接，请输入 mp.weixin.qq.com 域名的链接")

    params = parse_qs(parsed.query)

    return {
        "url": url,
        "is_short": is_short_url(url),
        "biz": _extract_param(params, "__biz"),
        "mid": _extract_param(params, "mid"),
        "idx": _extract_param(params, "idx"),
        "sn": _extract_param(params, "sn"),
    }


def _extract_param(params: dict, key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def is_valid_wechat_url(url: str) -> bool:
    """检查是否为有效的微信公众号文章链接"""
    try:
        parsed = urlparse(url.strip())
        return "mp.weixin.qq.com" in parsed.netloc and "/s" in parsed.path
    except Exception:
        return False


def build_profile_url(biz: str) -> str:
    """根据 biz 构造公众号历史消息页 URL"""
    return PROFILE_EXT_URL.format(biz=biz)


async def resolve_short_url(url: str) -> dict:
    """
    通过 Playwright 访问短链接，获取 __biz 和公众号名称。
    使用微信移动端 UA 以确保页面正确渲染。
    """
    from playwright.async_api import async_playwright

    result = {"biz": None, "nickname": None, "full_url": None}

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=WECHAT_MOBILE_UA,
        viewport={"width": 390, "height": 844},
    )
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        final_url = page.url
        result["full_url"] = final_url

        # 方法1：从重定向后的 URL 提取 biz
        parsed = parse_article_url(final_url)
        if parsed.get("biz"):
            result["biz"] = parsed["biz"]

        # 方法2：从页面 JS 变量中提取 biz
        if not result["biz"]:
            biz = await page.evaluate("""
                () => {
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
