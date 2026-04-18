"""
将微信公众号文章导出为 PDF。

使用 Playwright 打开文章页面，等待渲染完成后导出为 PDF。
支持注入 CSS 优化打印效果（隐藏无关元素、优化排版）。
"""

import asyncio
import os
import random
import re

from playwright.async_api import async_playwright, BrowserContext, Page

from config import OUTPUT_DIR, PDF_OPTIONS, CRAWL_DELAY_MIN, CRAWL_DELAY_MAX
from core.storage import update_pdf_path


def _sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    if len(name) > 100:
        name = name[:100]
    return name or "untitled"


# 注入的 CSS：隐藏公众号文章页的非正文元素，优化打印排版
INJECT_CSS = """
/* 隐藏顶部/底部无关元素 */
#js_pc_qr_code, #js_share_source, .qr_code_pc,
.reward_area, .like_a_look, #js_toobar3, #content_bottom_area,
.original_area_primary, .original_primary_card,
#js_tags_preview_toast, .discuss_container,
#js_temp_bottom_area, #js_pc_qr_code_box,
.rich_media_tool, .weui-footer, .qr_code_pc_outer,
#js_article_comment, #comment_area,
.reward_qrcode_area, .reward_tips,
.original_area, .media_tool_meta {
    display: none !important;
}

/* 优化正文排版 */
.rich_media_content {
    max-width: 100% !important;
    padding: 0 !important;
}

.rich_media_area_primary {
    max-width: 100% !important;
}

body {
    background: white !important;
}
"""


async def export_single_article(
    context: BrowserContext,
    title: str,
    url: str,
    biz: str,
    output_dir: str = None,
) -> str | None:
    """
    将单篇文章导出为 PDF。

    Args:
        context: Playwright 浏览器上下文
        title: 文章标题
        url: 文章 URL
        biz: 公众号 biz 标识
        output_dir: 输出目录，默认使用全局配置

    Returns:
        str | None: PDF 文件路径，失败返回 None
    """
    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, _sanitize_filename(biz))
    os.makedirs(output_dir, exist_ok=True)

    filename = _sanitize_filename(title) + ".pdf"
    pdf_path = os.path.join(output_dir, filename)

    # 如果已存在则跳过
    if os.path.exists(pdf_path):
        update_pdf_path(url, pdf_path)
        return pdf_path

    page = await context.new_page()

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 注入打印优化 CSS
        await page.add_style_tag(content=INJECT_CSS)

        # 等待图片加载完成
        await page.evaluate("""
            async () => {
                const images = document.querySelectorAll('img[data-src]');
                images.forEach(img => {
                    if (img.dataset.src && !img.src.startsWith('http')) {
                        img.src = img.dataset.src;
                    }
                });
                // 等待所有图片加载
                await Promise.all(
                    Array.from(document.images)
                        .filter(img => !img.complete)
                        .map(img => new Promise(resolve => {
                            img.onload = resolve;
                            img.onerror = resolve;
                        }))
                );
            }
        """)

        # 额外等待确保渲染完成
        await page.wait_for_timeout(1500)

        # 导出 PDF
        await page.pdf(path=pdf_path, **PDF_OPTIONS)

        update_pdf_path(url, pdf_path)
        return pdf_path

    except Exception as e:
        print(f"导出失败 [{title}]: {e}")
        return None
    finally:
        await page.close()


async def export_articles_to_pdf(
    context: BrowserContext,
    articles: list[dict],
    biz: str,
    nickname: str = None,
    progress_callback=None,
    output_dir: str = None,
) -> list[dict]:
    """
    批量导出文章为 PDF。

    Args:
        context: Playwright 浏览器上下文
        articles: 文章列表 [{"title": ..., "url": ...}, ...]
        biz: 公众号 biz 标识
        nickname: 公众号名称（用于目录名）
        progress_callback: 进度回调 callback(current, total, title)
        output_dir: 自定义输出目录，为 None 时自动按公众号名生成

    Returns:
        list[dict]: 导出结果列表 [{"title": ..., "pdf_path": ..., "success": bool}, ...]
    """
    if output_dir is None:
        dir_name = _sanitize_filename(nickname) if nickname else _sanitize_filename(biz)
        output_dir = os.path.join(OUTPUT_DIR, dir_name)
    os.makedirs(output_dir, exist_ok=True)

    results = []
    total = len(articles)

    for i, article in enumerate(articles):
        title = article.get("title", "untitled")
        url = article.get("url", "")

        if progress_callback:
            progress_callback(i, total, title)

        pdf_path = await export_single_article(
            context, title, url, biz, output_dir
        )

        results.append({
            "title": title,
            "url": url,
            "pdf_path": pdf_path,
            "success": pdf_path is not None,
        })

        # 随机延时
        if i < total - 1:
            delay = random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX)
            await asyncio.sleep(delay)

    if progress_callback:
        progress_callback(total, total, "完成")

    return results
