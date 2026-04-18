"""
微信公众号文章列表爬取器（无需登录版本）

通过 Playwright 模拟微信内置浏览器访问文章页面，
从公众号历史消息页（profile_ext）获取文章列表。
不需要登录微信公众平台后台，任何微信用户都能使用。

流程：
1. 用微信移动端 UA 打开一篇文章
2. 提取公众号 biz 和名称
3. 构造 profile_ext 页面 URL
4. 拦截 AJAX 分页请求，解析文章列表 JSON
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
    """
    创建模拟微信内置浏览器的 Playwright 上下文。
    使用微信移动端 UA，无需登录。
    """
    browser = await playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=WECHAT_MOBILE_UA,
        viewport={"width": 390, "height": 844},
    )
    await _load_cookies(context)
    return browser, context


# ──────────────────────────────────────────────
# 从文章页提取公众号信息
# ──────────────────────────────────────────────

async def extract_account_info(context: BrowserContext, article_url: str) -> dict:
    """
    访问文章页面，提取公众号 biz 和名称。

    Returns:
        {"biz": str, "nickname": str}
    """
    page = await context.new_page()
    result = {"biz": None, "nickname": None}

    try:
        await page.goto(article_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        # 提取 biz
        biz = await page.evaluate("""
            () => {
                const html = document.documentElement.innerHTML;
                // 从 JS 变量中提取
                let match = html.match(/var\\s+biz\\s*=\\s*["']([^"']+)["']/);
                if (match) return match[1];
                match = html.match(/__biz[=:]\\s*["']?([A-Za-z0-9=+/]+)/);
                if (match) return match[1];
                // 从 URL 参数中提取
                const url = window.location.href;
                const m = url.match(/__biz=([A-Za-z0-9=+/]+)/);
                if (m) return m[1];
                return null;
            }
        """)
        result["biz"] = biz

        # 提取公众号名称
        nickname = await page.evaluate("""
            () => {
                const el = document.getElementById('js_name')
                    || document.querySelector('.rich_media_meta_nickname .profile_nickname')
                    || document.querySelector('a.weui-wa-hotarea')
                    || document.querySelector('#profileBt');
                return el ? el.textContent.trim() : null;
            }
        """)
        result["nickname"] = nickname

    except Exception as e:
        print(f"提取公众号信息失败: {e}")
    finally:
        await page.close()

    return result


# ──────────────────────────────────────────────
# 从 profile_ext 获取文章列表
# ──────────────────────────────────────────────

def _parse_article_list(general_msg_list_str: str) -> list[dict]:
    """
    解析 profile_ext 返回的 general_msg_list JSON 字符串。
    处理单篇推送和多篇推送（multi_app_msg_item_list）。
    """
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


async def crawl_articles_via_profile(
    context: BrowserContext,
    biz: str,
    max_count: int = None,
    start_date: str = None,
    end_date: str = None,
    progress_callback=None,
) -> list[dict]:
    """
    通过 profile_ext 页面获取公众号文章列表。

    原理：打开公众号历史消息页，拦截 AJAX 分页请求（action=getmsg），
    解析返回的 JSON 获取文章列表。通过模拟滚动触发加载更多。

    Args:
        context: Playwright 浏览器上下文（微信 UA）
        biz: 公众号 __biz 标识
        max_count: 最大获取数量，None 表示全部
        start_date: 发布开始日期 "YYYY-MM-DD"
        end_date: 发布结束日期 "YYYY-MM-DD"
        progress_callback: 进度回调 callback(current, total_hint)
    """

    def _in_date_range(publish_time: str) -> bool:
        if not publish_time:
            return True
        d = publish_time[:10]
        if start_date and d < start_date:
            return False
        if end_date and d > end_date:
            return False
        return True

    def _before_start_date(publish_time: str) -> bool:
        if not start_date or not publish_time:
            return False
        return publish_time[:10] < start_date

    all_articles = []
    can_continue = True

    # 用来收集 AJAX 响应中的文章
    ajax_articles = []
    ajax_done = asyncio.Event()
    ajax_can_continue = [True]

    async def handle_response(response):
        """拦截 profile_ext?action=getmsg 的响应"""
        url = response.url
        if "profile_ext" in url and "action=getmsg" in url:
            try:
                data = await response.json()
                msg_list = data.get("general_msg_list", "")
                parsed = _parse_article_list(msg_list)
                ajax_articles.extend(parsed)

                if data.get("can_msg_continue") != 1:
                    ajax_can_continue[0] = False
            except Exception:
                ajax_can_continue[0] = False
            finally:
                ajax_done.set()

    page = await context.new_page()
    page.on("response", handle_response)

    try:
        # 打开 profile_ext 页面
        profile_url = (
            f"https://mp.weixin.qq.com/mp/profile_ext?"
            f"action=home&__biz={biz}&scene=124#wechat_redirect"
        )
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # 保存 Cookie 供后续使用
        await _save_cookies(page.context)

        # 首次加载的文章可能在页面 HTML 中
        initial_articles_str = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    const text = s.textContent;
                    const match = text.match(/var\\s+msgList\\s*=\\s*['"](.+?)['"]\\s*;/);
                    if (match) {
                        return match[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&');
                    }
                    // 另一种格式
                    const match2 = text.match(/var\\s+msgList\\s*=\\s*(\\{.+?\\})\\s*;/s);
                    if (match2) {
                        return match2[1];
                    }
                }
                return null;
            }
        """)

        if initial_articles_str:
            initial = _parse_article_list(initial_articles_str)
            for a in initial:
                if max_count and len(all_articles) >= max_count:
                    break
                if _before_start_date(a["publish_time"]):
                    can_continue = False
                    break
                if _in_date_range(a["publish_time"]):
                    insert_article(biz=biz, **{k: a[k] for k in
                        ["title", "url", "author", "digest", "cover_url", "publish_time"]})
                    all_articles.append(a)

        if progress_callback:
            progress_callback(len(all_articles), max_count or 0)

        # 滚动加载更多
        scroll_count = 0
        max_empty_scrolls = 3
        empty_scrolls = 0

        while can_continue:
            if max_count and len(all_articles) >= max_count:
                break
            if not ajax_can_continue[0]:
                break

            # 清空状态，准备接收下一批
            ajax_articles.clear()
            ajax_done.clear()

            # 滚动到底部触发加载
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            scroll_count += 1

            # 等待 AJAX 响应
            try:
                await asyncio.wait_for(ajax_done.wait(), timeout=10)
            except asyncio.TimeoutError:
                empty_scrolls += 1
                if empty_scrolls >= max_empty_scrolls:
                    break
                continue

            empty_scrolls = 0

            if not ajax_articles:
                break

            # 处理这一批文章
            stop = False
            for a in ajax_articles:
                if max_count and len(all_articles) >= max_count:
                    break
                if _before_start_date(a["publish_time"]):
                    stop = True
                    break
                if _in_date_range(a["publish_time"]):
                    insert_article(biz=biz, **{k: a[k] for k in
                        ["title", "url", "author", "digest", "cover_url", "publish_time"]})
                    all_articles.append(a)

            if stop:
                break

            if progress_callback:
                progress_callback(len(all_articles), max_count or 0)

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
