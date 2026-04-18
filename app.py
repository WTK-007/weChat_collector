"""
微信公众号文章提取器 - Streamlit 可视化界面（无需登录版本）

三步操作：
1. 输入文章链接 → 自动识别公众号
2. 采集文章列表（支持日期/篇数筛选）→ 勾选要导出的文章
3. 导出为 PDF
"""

import asyncio
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from config import OUTPUT_DIR
from core.parser import parse_article_url, is_valid_wechat_url, resolve_short_url
from core.storage import init_db, upsert_account, get_articles, get_article_count

init_db()

# ──────────────────────────────────────────────
# 页面配置
# ──────────────────────────────────────────────

st.set_page_config(page_title="公众号文章提取器", page_icon="📰", layout="wide")
st.title("📰 微信公众号文章提取器")
st.caption("输入任意一篇公众号文章链接，自动获取文章列表并导出为 PDF（无需登录）")

# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────

for key, default in {
    "biz": None,
    "nickname": None,
    "articles_fetched": False,
    "crawl_running": False,
    "export_running": False,
    "selected_articles": [],
    "select_all_state": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────
# Step 1: 输入文章链接
# ──────────────────────────────────────────────

st.header("① 输入文章链接")

if st.session_state.biz:
    nickname_display = st.session_state.nickname or st.session_state.biz
    st.success(f"✅ 已识别公众号: **{nickname_display}**（biz: `{st.session_state.biz}`）")
    if st.button("🔄 更换公众号"):
        st.session_state.biz = None
        st.session_state.nickname = None
        st.session_state.articles_fetched = False
        st.session_state.selected_articles = []
        st.session_state.select_all_state = None
        st.rerun()
else:
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        article_url = st.text_input(
            "粘贴文章链接",
            placeholder="https://mp.weixin.qq.com/s/xxxxxx",
            label_visibility="collapsed",
        )
    with col_btn:
        parse_clicked = st.button("🔍 识别公众号", type="primary", use_container_width=True)

    if parse_clicked and article_url:
        if not is_valid_wechat_url(article_url):
            st.error("❌ 不是有效的微信公众号文章链接")
        else:
            parsed = parse_article_url(article_url)
            biz = parsed.get("biz")

            if biz:
                # 长链接，直接拿到 biz，再访问页面提取名称
                with st.spinner("正在识别公众号..."):
                    async def _extract_info():
                        from playwright.async_api import async_playwright
                        from core.crawler import create_wechat_context, extract_account_info
                        p = await async_playwright().start()
                        browser, ctx = await create_wechat_context(p, headless=True)
                        info = await extract_account_info(ctx, article_url)
                        await browser.close()
                        await p.stop()
                        return info

                    info = run_async(_extract_info())
                    st.session_state.biz = biz
                    if info.get("nickname"):
                        st.session_state.nickname = info["nickname"]
                        upsert_account(biz, info["nickname"])
                    st.rerun()

            elif parsed.get("is_short"):
                with st.spinner("🔗 正在解析短链接..."):
                    try:
                        resolved = run_async(resolve_short_url(article_url))
                        biz = resolved.get("biz")
                        if biz:
                            st.session_state.biz = biz
                            if resolved.get("nickname"):
                                st.session_state.nickname = resolved["nickname"]
                                upsert_account(biz, resolved["nickname"])
                            st.rerun()
                        else:
                            st.error("❌ 无法识别公众号，请换一篇文章链接")
                    except Exception as e:
                        st.error(f"❌ 解析失败: {e}")
            else:
                st.error("❌ 无法识别公众号，请换一篇文章链接")
    elif parse_clicked:
        st.warning("请先粘贴文章链接")


# ──────────────────────────────────────────────
# Step 2: 采集文章列表
# ──────────────────────────────────────────────

st.header("② 采集文章列表")

if not st.session_state.biz:
    st.info("请先在上方输入文章链接")
else:
    from datetime import date

    biz = st.session_state.biz
    existing_count = get_article_count(biz)

    if existing_count > 0:
        st.success(f"📊 已采集到 **{existing_count}** 篇文章")

    st.markdown("---")

    # 采集模式
    crawl_mode = st.radio("采集方式", ["全部", "最近 N 篇", "按发布日期范围"], horizontal=True, key="crawl_mode")

    crawl_max_count = None
    crawl_start_date = None
    crawl_end_date = None

    if crawl_mode == "最近 N 篇":
        crawl_max_count = st.number_input("采集最近多少篇", min_value=1, max_value=10000, value=20, step=5)
    elif crawl_mode == "按发布日期范围":
        col_s, col_e = st.columns(2)
        with col_s:
            crawl_start_date = st.date_input("开始日期", value=date(2024, 1, 1), key="crawl_start")
        with col_e:
            crawl_end_date = st.date_input("结束日期", value=date.today(), key="crawl_end")

    # 按钮文字
    if crawl_mode == "最近 N 篇":
        btn_label = f"📥 采集最近 {crawl_max_count} 篇"
    elif crawl_mode == "按发布日期范围":
        btn_label = f"📥 采集 {crawl_start_date} ~ {crawl_end_date}"
    else:
        btn_label = "📥 采集全部文章"

    if st.button(btn_label, disabled=st.session_state.crawl_running, type="primary"):
        st.session_state.crawl_running = True
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            async def do_crawl():
                from playwright.async_api import async_playwright
                from core.crawler import create_wechat_context, crawl_articles_via_profile

                p = await async_playwright().start()
                browser, ctx = await create_wechat_context(p, headless=True)

                status_text.text("正在采集文章列表...")

                def on_progress(current, total_hint):
                    if total_hint > 0:
                        progress_bar.progress(min(current / total_hint, 1.0))
                    status_text.text(f"已采集 {current} 篇...")

                articles = await crawl_articles_via_profile(
                    ctx, biz,
                    max_count=crawl_max_count,
                    start_date=crawl_start_date.strftime("%Y-%m-%d") if crawl_start_date else None,
                    end_date=crawl_end_date.strftime("%Y-%m-%d") if crawl_end_date else None,
                    progress_callback=on_progress,
                )

                # 更新公众号名称（如果之前没有）
                if not st.session_state.nickname and articles:
                    from core.crawler import extract_account_info
                    info = await extract_account_info(ctx, articles[0]["url"])
                    if info.get("nickname"):
                        st.session_state.nickname = info["nickname"]
                        upsert_account(biz, info["nickname"])

                await browser.close()
                await p.stop()
                return len(articles)

            count = run_async(do_crawl())
            st.session_state.articles_fetched = True
            progress_bar.progress(1.0)
            status_text.text("")
            st.success(f"✅ 采集完成！共 {count} 篇文章")
            st.rerun()

        except Exception as e:
            st.error(f"❌ 采集失败: {e}")
        finally:
            st.session_state.crawl_running = False

    # ──────────────────────────────────────────
    # 文章列表
    # ──────────────────────────────────────────

    all_articles = get_articles(biz)

    if all_articles:
        import pandas as pd

        st.markdown("---")

        search_term = st.text_input("🔍 搜索标题关键词", "", key="search_articles")
        filtered = all_articles
        if search_term:
            filtered = [a for a in filtered if search_term.lower() in a.get("title", "").lower()]

        st.subheader(f"文章列表（{len(filtered)} 篇）")

        if not filtered:
            st.warning("当前条件下没有文章")
        else:
            col_sel1, col_sel2, _ = st.columns([1, 1, 4])
            with col_sel1:
                if st.button("全选"):
                    st.session_state.select_all_state = True
            with col_sel2:
                if st.button("取消全选"):
                    st.session_state.select_all_state = False

            df_data = []
            for idx, a in enumerate(filtered):
                if st.session_state.select_all_state is True:
                    checked = True
                elif st.session_state.select_all_state is False:
                    checked = False
                else:
                    checked = not bool(a.get("pdf_path"))

                df_data.append({
                    "选择": checked,
                    "编号": idx + 1,
                    "文章标题": a.get("title", ""),
                    "文章链接": a.get("url", ""),
                    "发布日期": (a.get("publish_time") or "")[:10],
                    "PDF状态": "✅ 已导出" if a.get("pdf_path") else "—",
                })

            df = pd.DataFrame(df_data)

            edited_df = st.data_editor(
                df,
                column_config={
                    "选择": st.column_config.CheckboxColumn("选择", default=True, width="small"),
                    "编号": st.column_config.NumberColumn("编号", width="small"),
                    "文章标题": st.column_config.TextColumn("文章标题", width="large"),
                    "文章链接": st.column_config.LinkColumn("文章链接", width="medium", display_text="打开链接"),
                    "发布日期": st.column_config.TextColumn("发布日期", width="small"),
                    "PDF状态": st.column_config.TextColumn("PDF状态", width="small"),
                },
                disabled=["编号", "文章标题", "文章链接", "发布日期", "PDF状态"],
                hide_index=True,
                use_container_width=True,
                key="article_table",
            )

            selected_mask = edited_df["选择"].tolist()
            selected_articles = [filtered[i] for i, sel in enumerate(selected_mask) if sel]
            st.info(f"已勾选 **{len(selected_articles)}** 篇文章")
            st.session_state.selected_articles = selected_articles

            # ──────────────────────────────────
            # Step 3: 导出 PDF
            # ──────────────────────────────────

            st.header("③ 导出 PDF")

            default_dir = os.path.join(OUTPUT_DIR, st.session_state.nickname or biz)
            save_path = st.text_input(
                "📁 PDF 保存路径",
                value=default_dir,
                help="文件将保存到该目录下，可修改为任意路径",
            )

            if not selected_articles:
                st.warning("请先在上方列表中勾选要导出的文章")
            else:
                st.markdown(f"将导出 **{len(selected_articles)}** 篇文章为 PDF → `{save_path}`")

                if st.button("📄 确认导出 PDF", disabled=st.session_state.export_running, type="primary"):
                    st.session_state.export_running = True
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    try:
                        async def do_export():
                            from playwright.async_api import async_playwright
                            from core.crawler import create_wechat_context
                            from core.pdf_exporter import export_articles_to_pdf

                            p = await async_playwright().start()
                            browser, ctx = await create_wechat_context(p, headless=True)

                            def on_progress(current, total, title):
                                if total > 0:
                                    progress_bar.progress(current / total)
                                status_text.text(f"[{current}/{total}] {title}")

                            results = await export_articles_to_pdf(
                                ctx, selected_articles, biz,
                                nickname=st.session_state.nickname,
                                progress_callback=on_progress,
                                output_dir=save_path,
                            )

                            await browser.close()
                            await p.stop()
                            return results

                        results = run_async(do_export())
                        success_count = sum(1 for r in results if r["success"])
                        fail_count = len(results) - success_count

                        progress_bar.progress(1.0)
                        status_text.text("")
                        st.success(f"✅ 导出完成！成功 {success_count} 篇，失败 {fail_count} 篇")
                        st.info(f"📁 文件保存在: `{save_path}`")

                        if fail_count > 0:
                            with st.expander(f"查看 {fail_count} 篇失败详情"):
                                for r in results:
                                    if not r["success"]:
                                        st.write(f"- {r['title']}")
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ 导出失败: {e}")
                    finally:
                        st.session_state.export_running = False


# ──────────────────────────────────────────────
# 侧边栏
# ──────────────────────────────────────────────

with st.sidebar:
    st.header("ℹ️ 使用说明")
    st.markdown("""
    **三步操作：**
    1. 粘贴公众号文章链接，点击识别
    2. 选择采集方式，点击采集
    3. 勾选文章，导出 PDF

    **无需登录公众平台！**
    不需要拥有公众号，任何人都能使用。

    **注意事项：**
    - 采集速度约 2-5 秒/页
    - PDF 导出逐篇渲染，速度较慢
    """)

    st.divider()

    st.header("⚙️ 状态")
    st.write(f"公众号: {st.session_state.nickname or '未识别'}")
    st.write(f"输出目录: `{OUTPUT_DIR}`")
