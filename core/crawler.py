"""
微信公众号文章列表爬取器（无需登录版本）

通过 Playwright 模拟微信内置浏览器：
1. 先访问一篇文章页面，建立微信 session/cookie
2. 然后直接调用 profile_ext?action=getmsg API 分页获取文章列表

不需要登录微信公众平台后台，任何人都能使用。
"""

import asyncio
import json
import os
import random
from datetime import datetime

from playwright.async_api import async_playwright, BrowserContext, Page

from config import WECHAT_MOBILE_UA, CRAWL_DELAY_MIN, CRAWL_DELAY_MAX
from core.storage import insert_article

COOKIE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cookies.json")


# ──────────────────────────────────────────────
# 浏览器上下文
# ──────────────────────────────────────────────

async def _save_cookies(context: BrowserContext):
    cookies = await context.cookies()
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


async def _load_cookies(context: BrowserContext) -> bool:
    if not os.path.exists(COOKIE_PATH):
        return False
    try:
        with open(COOKIE_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def create_wechat_context(playwright, headless: bool = True):
    """创建模拟微信内置浏览器的上下文"""
    browser = await playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=WECHAT_MOBILE_UA,
        viewport={"width": 390, "height": 844},
        extra_http_headers={
            "X-Requested-With": "com.tencent.mm",
        },
    )
    await _load_cookies(context)
    return browser, context


# ──────────────────────────────────────────────
# 从文章页提取公众号信息
# ──────────────────────────────────────────────

async def extract_account_info(context: BrowserContext, article_url: str) -> dict:
    """访问文章页，提取 biz 和公众号名称"""
    page = await context.new_page()
    result = {"biz": None, "nickname": None}

    try:
        await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        result["biz"] = await page.evaluate("""
            () => {
                const html = document.documentElement.innerHTML;
                let m = html.match(/var\\s+biz\\s*=\\s*["']([^"']+)["']/);
                if (m) return m[1];
                m = html.match(/__biz=([A-Za-z0-9=+/]+)/);
                if (m) return m[1];
                return null;
            }
        """)

        result["nickname"] = await page.evaluate("""
            () => {
                const el = document.getElementById('js_name')
                    || document.querySelector('.rich_media_meta_nickname .profile_nickname')
                    || document.querySelector('#profileBt');
                return el ? el.textContent.trim() : null;
            }
        """)
    except Exception as e:
        print(f"提取公众号信息失败: {e}")
    finally:
        await page.close()

    return result


# ──────────────────────────────────────────────
# 解析文章列表 JSON
# ──────────────────────────────────────────────

def _parse_article_list(general_msg_list_str: str) -> list[dict]:
    """解析 getmsg 返回的 general_msg_list JSON"""
    articles = []

    try:
        data = json.loads(general_msg_list_str)
    except (json.JSONDecodeError, TypeError):
        return articles

    for item in data.get("list", []):
        comm_info = item.get("comm_msg_info", {})
        publish_ts = comm_info.get("datetime", 0)
        publish_time = (
            datetime.fromtimestamp(publish_ts).strftime("%Y-%m-%d %H:%M:%S")
            if publish_ts else None
        )

        ext_info = item.get("app_msg_ext_info", {})
        if not ext_info:
            continue

        # 主文章
        title = ext_info.get("title", "")
        content_url = ext_info.get("content_url", "").replace("&amp;", "&")
        if title and content_url:
            articles.append({
                "title": title,
                "url": content_url,
                "author": ext_info.get("author", ""),
                "digest": ext_info.get("digest", ""),
                "cover_url": ext_info.get("cover", ""),
                "publish_time": publish_time,
            })

        # 多篇推送中的其他文章
        for sub in ext_info.get("multi_app_msg_item_list", []):
            sub_title = sub.get("title", "")
            sub_url = sub.get("content_url", "").replace("&amp;", "&")
            if sub_title and sub_url:
                articles.append({
                    "title": sub_title,
                    "url": sub_url,
                    "author": sub.get("author", ""),
                    "digest": sub.get("digest", ""),
                    "cover_url": sub.get("cover", ""),
                    "publish_time": publish_time,
                })

    return articles


# ──────────────────────────────────────────────
# 采集文章列表
# ──────────────────────────────────────────────

async def _init_session(context: BrowserContext, article_url: str) -> Page:
    """
    先访问一篇文章页面建立微信 session cookie，
    这是后续调用 profile_ext API 的前提。
    """
    page = await context.new_page()
    await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(2000)
    await _save_cookies(context)
    return page


async def _fetch_getmsg(
    page: Page,
    biz: str,
    offset: int = 0,
    count: int = 10,
) -> dict:
    """
    直接调用 profile_ext?action=getmsg API 获取一页文章。

    返回: {"articles": [...], "next_offset": int, "can_continue": bool}
    """
    url = (
        f"https://mp.weixin.qq.com/mp/profile_ext?"
        f"action=getmsg&__biz={biz}&f=json&offset={offset}"
        f"&count={count}&is_ok=1&scene=124"
        f"&uin=777&key=777"
    )

    result = {"articles": [], "next_offset": offset + count, "can_continue": False}

    try:
        response = await page.request.get(url)
        data = await response.json()

        if data.get("ret") != 0 and data.get("errmsg", "") != "ok":
            print(f"getmsg API 返回错误: ret={data.get('ret')}, errmsg={data.get('errmsg')}")
            return result

        msg_list = data.get("general_msg_list", "")
        result["articles"] = _parse_article_list(msg_list)
        result["next_offset"] = data.get("next_offset", offset + count)
        result["can_continue"] = data.get("can_msg_continue", 0) == 1

    except Exception as e:
        print(f"getmsg 请求失败: {e}")

    return result


async def crawl_articles_via_profile(
    context: BrowserContext,
    biz: str,
    article_url: str = None,
    max_count: int = None,
    start_date: str = None,
    end_date: str = None,
    progress_callback=None,
) -> list[dict]:
    """
    通过 profile_ext getmsg API 获取公众号文章列表。

    流程：
    1. 先访问一篇文章建立 session
    2. 直接调用 getmsg API 分页获取文章
    3. 不需要滚动页面，直接 API 调用更稳定

    Args:
        context: 微信 UA 浏览器上下文
        biz: 公众号 __biz
        article_url: 用于建立 session 的文章 URL
        max_count: 最大获取数量
        start_date: 开始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"
        progress_callback: 进度回调 callback(current, total_hint)
    """

    def _in_date_range(pt: str) -> bool:
        if not pt:
            return True
        d = pt[:10]
        if start_date and d < start_date:
            return False
        if end_date and d > end_date:
            return False
        return True

    def _before_start(pt: str) -> bool:
        if not start_date or not pt:
            return False
        return pt[:10] < start_date

    # 建立 session
    if article_url:
        page = await _init_session(context, article_url)
    else:
        # 没有文章 URL 时，构造一个 profile_ext 首页访问
        page = await context.new_page()
        profile_url = (
            f"https://mp.weixin.qq.com/mp/profile_ext?"
            f"action=home&__biz={biz}&scene=124#wechat_redirect"
        )
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        await _save_cookies(context)

    all_articles = []
    offset = 0

    if progress_callback:
        progress_callback(0, max_count or 0)

    try:
        while True:
            if max_count and len(all_articles) >= max_count:
                break

            page_data = await _fetch_getmsg(page, biz, offset=offset)

            if not page_data["articles"]:
                # 如果第一页就没数据，可能是 session 问题，打印调试信息
                if offset == 0:
                    print(f"[警告] 首页无数据，可能 session 未建立或 biz 无效: {biz}")
                break

            stop = False
            for a in page_data["articles"]:
                if max_count and len(all_articles) >= max_count:
                    break
                if _before_start(a["publish_time"]):
                    stop = True
                    break
                if _in_date_range(a["publish_time"]):
                    insert_article(biz=biz, **{k: a[k] for k in
                        ["title", "url", "author", "digest", "cover_url", "publish_time"]})
                    all_articles.append(a)

            if progress_callback:
                progress_callback(len(all_articles), max_count or 0)

            if stop or not page_data["can_continue"]:
                break

            offset = page_data["next_offset"]

            # 随机延时
            delay = random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX)
            await asyncio.sleep(delay)

        if progress_callback:
            progress_callback(len(all_articles), len(all_articles))

    except Exception as e:
        print(f"采集失败: {e}")
        raise
    finally:
        await page.close()

    return all_articles
