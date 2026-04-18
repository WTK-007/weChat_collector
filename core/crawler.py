"""
微信公众号文章列表爬取器

通过 Playwright 模拟登录微信公众平台后台，获取文章列表。
流程：
1. 打开公众平台登录页，用户扫码登录
2. 保存登录 Cookie 供后续使用
3. 调用后台 API 分页获取指定公众号的文章列表
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime

from playwright.async_api import async_playwright, Page, BrowserContext

from config import (
    MP_LOGIN_URL,
    MP_ARTICLE_LIST_API,
    CRAWL_DELAY_MIN,
    CRAWL_DELAY_MAX,
    PAGE_SIZE,
)
from core.storage import upsert_account, insert_article

COOKIE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cookies.json")


async def _save_cookies(context: BrowserContext):
    """保存浏览器 Cookie 到本地文件"""
    cookies = await context.cookies()
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


async def _load_cookies(context: BrowserContext) -> bool:
    """从本地文件加载 Cookie，返回是否成功"""
    if not os.path.exists(COOKIE_PATH):
        return False
    try:
        with open(COOKIE_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def login_and_get_context(playwright, headless: bool = False):
    """
    登录微信公众平台，返回已登录的 browser 和 context。
    如果有保存的 Cookie 则尝试复用，否则打开浏览器让用户扫码。
    """
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )

    # 尝试加载已有 Cookie
    has_cookies = await _load_cookies(context)
    page = await context.new_page()

    if has_cookies:
        # 检查 Cookie 是否仍然有效
        await page.goto(MP_LOGIN_URL)
        await page.wait_for_timeout(2000)
        current_url = page.url
        if "cgi-bin/home" in current_url or "cgi-bin/frame" in current_url:
            return browser, context, page
        # Cookie 失效，需要重新登录

    # 打开登录页面等待扫码
    await page.goto(MP_LOGIN_URL)
    return browser, context, page


async def wait_for_login(page: Page, timeout: int = 120) -> bool:
    """
    等待用户扫码登录成功。
    微信登录流程：扫码 → 手机确认 → 可能有验证码 → 跳转后台首页。
    通过轮询检测页面 URL 变化来判断是否登录成功。
    """
    import time
    start = time.time()
    # 登录成功后 URL 中会包含这些关键词
    success_patterns = ["cgi-bin/home", "cgi-bin/frame", "cgi-bin/loginpage"]

    while time.time() - start < timeout:
        current_url = page.url
        for pattern in success_patterns:
            if pattern in current_url:
                # 到达 loginpage 说明扫码成功但还在中间页，等待最终跳转
                if "loginpage" in current_url:
                    try:
                        await page.wait_for_url(
                            lambda url: "cgi-bin/home" in url or "cgi-bin/frame" in url,
                            timeout=30000,
                        )
                    except Exception:
                        pass
                    # 再次检查
                    final_url = page.url
                    if "cgi-bin/home" in final_url or "cgi-bin/frame" in final_url:
                        return True
                    # 即使没跳转到 home，loginpage 也说明扫码成功了
                    return True
                return True

        # 每秒检查一次
        await page.wait_for_timeout(1000)

    return False


async def _get_token(page: Page) -> str | None:
    """从当前页面 URL 中提取 token 参数"""
    url = page.url
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    tokens = params.get("token")
    if tokens:
        return tokens[0]

    # 尝试从页面中获取
    try:
        token = await page.evaluate("""
            () => {
                const match = document.cookie.match(/token=(\\d+)/);
                return match ? match[1] : null;
            }
        """)
        return token
    except Exception:
        return None


async def _search_biz_and_get_fakeid(page: Page, token: str, nickname: str, biz: str = None) -> dict | None:
    """
    通过公众平台后台按公众号名称搜索，获取其 fakeid（后台内部 ID）。

    Args:
        page: 浏览器页面
        token: 登录 token
        nickname: 公众号名称（用于搜索）
        biz: 公众号 biz 标识（用于在搜索结果中做二次验证）
    """
    from urllib.parse import quote

    search_url = (
        f"https://mp.weixin.qq.com/cgi-bin/searchbiz?"
        f"action=search_biz&begin=0&count=5&"
        f"token={token}&lang=zh_CN&f=json&ajax=1&"
        f"query={quote(nickname)}"
    )

    response = await page.request.get(search_url)
    data = await response.json()

    if data.get("base_resp", {}).get("ret") == 0:
        biz_list = data.get("list", [])
        if not biz_list:
            return None

        # 如果有 biz，在结果中找匹配的
        if biz:
            for item in biz_list:
                # 微信返回的 fakeid 对应的 biz 无法直接比较
                # 但名称精确匹配是最可靠的
                if item.get("nickname") == nickname:
                    return {
                        "fakeid": item.get("fakeid"),
                        "nickname": item.get("nickname"),
                        "alias": item.get("alias"),
                        "round_head_img": item.get("round_head_img"),
                    }

        # 没有精确匹配就取第一个结果
        item = biz_list[0]
        return {
            "fakeid": item.get("fakeid"),
            "nickname": item.get("nickname"),
            "alias": item.get("alias"),
            "round_head_img": item.get("round_head_img"),
        }

    return None


async def fetch_article_list(
    page: Page,
    token: str,
    fakeid: str,
    begin: int = 0,
    count: int = PAGE_SIZE,
) -> dict:
    """
    获取公众号文章列表（单页）。

    返回:
        dict: {
            "articles": [...],
            "total": int,
        }
    """
    url = (
        f"{MP_ARTICLE_LIST_API}?"
        f"action=list_ex&begin={begin}&count={count}&"
        f"fakeid={fakeid}&type=9&query=&"
        f"token={token}&lang=zh_CN&f=json&ajax=1"
    )

    response = await page.request.get(url)
    data = await response.json()

    result = {"articles": [], "total": 0}

    if data.get("base_resp", {}).get("ret") == 0:
        result["total"] = data.get("app_msg_cnt", 0)
        for item in data.get("app_msg_list", []):
            article = {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "author": item.get("author", ""),
                "digest": item.get("digest", ""),
                "cover_url": item.get("cover", ""),
                "publish_time": datetime.fromtimestamp(
                    item.get("update_time", 0)
                ).strftime("%Y-%m-%d %H:%M:%S") if item.get("update_time") else None,
            }
            result["articles"].append(article)

    return result


async def crawl_all_articles(
    page: Page,
    token: str,
    fakeid: str,
    biz: str,
    max_count: int = None,
    progress_callback=None,
    start_date: str = None,
    end_date: str = None,
) -> list[dict]:
    """
    分页爬取公众号的全部（或指定数量）文章列表。

    Args:
        page: Playwright 页面对象
        token: 登录 token
        fakeid: 公众号后台 fakeid
        biz: 公众号 biz 标识
        max_count: 最大获取数量，None 表示全部
        progress_callback: 进度回调函数 callback(current, total)
        start_date: 发布开始日期 "YYYY-MM-DD"，早于此日期的文章会被跳过
        end_date: 发布结束日期 "YYYY-MM-DD"，晚于此日期的文章会被跳过

    Returns:
        list[dict]: 文章列表
    """

    def _in_date_range(publish_time: str) -> bool:
        """检查文章发布日期是否在指定范围内"""
        if not publish_time:
            return True  # 无日期的文章默认包含
        article_date = publish_time[:10]  # "YYYY-MM-DD"
        if start_date and article_date < start_date:
            return False
        if end_date and article_date > end_date:
            return False
        return True

    def _before_start_date(publish_time: str) -> bool:
        """检查文章是否早于开始日期（用于提前终止翻页）"""
        if not start_date or not publish_time:
            return False
        return publish_time[:10] < start_date

    all_articles = []
    begin = 0
    stop_crawling = False

    # 先获取第一页以得到总数
    first_page = await fetch_article_list(page, token, fakeid, begin=0)
    total = first_page["total"]

    if max_count:
        total = min(total, max_count)

    if progress_callback:
        progress_callback(0, total)

    for article in first_page["articles"]:
        if max_count and len(all_articles) >= max_count:
            break
        # 文章按时间倒序排列，如果已经早于开始日期，后面的更早，可以停了
        if _before_start_date(article["publish_time"]):
            stop_crawling = True
            break
        if not _in_date_range(article["publish_time"]):
            continue
        insert_article(
            biz=biz,
            title=article["title"],
            url=article["url"],
            author=article["author"],
            digest=article["digest"],
            cover_url=article["cover_url"],
            publish_time=article["publish_time"],
        )
        all_articles.append(article)

    if progress_callback:
        progress_callback(len(all_articles), total)

    begin = PAGE_SIZE

    while not stop_crawling and begin < first_page["total"]:
        if max_count and len(all_articles) >= max_count:
            break

        # 随机延时，避免触发反爬
        delay = random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX)
        await asyncio.sleep(delay)

        page_data = await fetch_article_list(page, token, fakeid, begin=begin)

        if not page_data["articles"]:
            break

        for article in page_data["articles"]:
            if max_count and len(all_articles) >= max_count:
                break
            if _before_start_date(article["publish_time"]):
                stop_crawling = True
                break
            if not _in_date_range(article["publish_time"]):
                continue
            insert_article(
                biz=biz,
                title=article["title"],
                url=article["url"],
                author=article["author"],
                digest=article["digest"],
                cover_url=article["cover_url"],
                publish_time=article["publish_time"],
            )
            all_articles.append(article)

        if progress_callback:
            progress_callback(len(all_articles), total)

        begin += PAGE_SIZE

    return all_articles
