"""
微信公众号文章提取器 - Streamlit 可视化界面

功能：
1. 输入公众号文章链接，自动识别公众号
2. 登录微信公众平台获取文章列表
3. 批量导出文章为 PDF
"""

import asyncio
import os
import sys

import streamlit as st

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(__file__))

from config import OUTPUT_DIR
from core.parser import parse_article_url, is_valid_wechat_url, is_short_url, resolve_short_url
from core.storage import (
    init_db, upsert_account,
    get_articles, get_article_count,
)

# 初始化数据库
init_db()

# ──────────────────────────────────────────────
# 页面配置
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="公众号文章提取器",
    page_icon="📰",
    layout="wide",
)

st.title("📰 微信公众号文章提取器")
st.caption("输入任意一篇公众号文章链接，自动获取该公众号所有文章并导出为 PDF")

# ──────────────────────────────────────────────
# Session state 初始化
# ──────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "biz" not in st.session_state:
    st.session_state.biz = None
if "nickname" not in st.session_state:
    st.session_state.nickname = None
if "fakeid" not in st.session_state:
    st.session_state.fakeid = None
if "token" not in st.session_state:
    st.session_state.token = None
if "articles_fetched" not in st.session_state:
    st.session_state.articles_fetched = False
if "crawl_running" not in st.session_state:
    st.session_state.crawl_running = False
if "export_running" not in st.session_state:
    st.session_state.export_running = False
if "selected_articles" not in st.session_state:
    st.session_state.selected_articles = []


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def run_async(coro):
    """在 Streamlit 中运行异步函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────
# Step 1: 输入文章链接
# ──────────────────────────────────────────────

st.header("① 输入文章链接")

# 已识别时展示结果，并允许重新输入
if st.session_state.biz:
    nickname_display = st.session_state.nickname or st.session_state.biz
    st.success(f"✅ 已识别公众号: **{nickname_display}**（biz: `{st.session_state.biz}`）")
    if st.button("🔄 更换公众号"):
        st.session_state.biz = None
        st.session_state.nickname = None
        st.session_state.articles_fetched = False
        st.session_state.selected_articles = []
        st.rerun()
else:
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        article_url = st.text_input(
            "粘贴任意一篇该公众号的文章链接",
            placeholder="https://mp.weixin.qq.com/s/xxxxxx",
            label_visibility="collapsed",
        )
    with col_btn:
        parse_clicked = st.button("🔍 识别公众号", type="primary", use_container_width=True)

    if parse_clicked and article_url:
        if not is_valid_wechat_url(article_url):
            st.error("❌ 不是有效的微信公众号文章链接，请检查后重试")
        else:
            parsed = parse_article_url(article_url)
            biz = parsed.get("biz")

            if biz:
                st.session_state.biz = biz
                st.success(f"✅ 已识别公众号标识: `{biz}`")
                st.rerun()
            elif parsed.get("is_short"):
                with st.spinner("🔗 正在解析短链接，请稍候..."):
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
                            st.error("❌ 无法从该链接中识别公众号，请换一篇文章链接重试")
                    except Exception as e:
                        st.error(f"❌ 解析失败: {e}")
            else:
                st.error("❌ 无法从该链接中识别公众号，请换一篇文章链接重试")
    elif parse_clicked and not article_url:
        st.warning("请先粘贴文章链接")


# ──────────────────────────────────────────────
# Step 2: 登录微信公众平台
# ──────────────────────────────────────────────

st.header("② 登录微信公众平台")

if st.session_state.logged_in:
    st.success("✅ 已登录微信公众平台")
else:
    st.info("💡 点击下方按钮获取登录二维码，用微信扫码即可登录。")
    st.warning("⚠️ 你需要有一个公众号（任意订阅号/服务号均可），用绑定了该公众号的微信扫码。")

    if st.button("🔑 获取登录二维码"):
        qr_placeholder = st.empty()
        status_placeholder = st.empty()

        try:
            async def do_login_with_qr():
                from playwright.async_api import async_playwright
                from core.crawler import login_and_get_context, _save_cookies, _get_token
                import time

                p = await async_playwright().start()
                browser, context, page = await login_and_get_context(p, headless=True)

                # 检查是否已经登录（Cookie 有效）
                if "cgi-bin/home" in page.url or "cgi-bin/frame" in page.url:
                    token = await _get_token(page)
                    await _save_cookies(context)
                    await browser.close()
                    await p.stop()
                    return {"success": True, "token": token}

                # 等待二维码出现
                status_placeholder.text("正在加载二维码...")
                await page.wait_for_timeout(2000)

                # 截取二维码区域
                qr_element = await page.query_selector(".login__type__container__scan__qrcode, .qrcode img, .weui-desktop-qrcode img, img.login__type__container__scan__qrcode")

                if qr_element:
                    qr_bytes = await qr_element.screenshot()
                else:
                    # 如果找不到二维码元素，截取整个登录区域
                    login_area = await page.query_selector(".login__type__container__scan, .login_qrcode_area, .login__type__container")
                    if login_area:
                        qr_bytes = await login_area.screenshot()
                    else:
                        # 兜底：截取页面中央区域
                        qr_bytes = await page.screenshot(clip={"x": 300, "y": 100, "width": 400, "height": 400})

                # 显示二维码
                qr_placeholder.image(qr_bytes, caption="请用微信扫描此二维码登录", width=300)
                status_placeholder.info("⏳ 等待扫码... 扫码后请在手机上确认登录")

                # 轮询等待登录成功
                start = time.time()
                timeout = 120

                while time.time() - start < timeout:
                    current_url = page.url
                    if any(p in current_url for p in ["cgi-bin/home", "cgi-bin/frame"]):
                        break

                    if "loginpage" in current_url:
                        status_placeholder.info("⏳ 已扫码，等待确认...")
                        try:
                            await page.wait_for_url(
                                lambda url: "cgi-bin/home" in url or "cgi-bin/frame" in url,
                                timeout=30000,
                            )
                        except Exception:
                            pass
                        break

                    await page.wait_for_timeout(1500)

                # 检查是否登录成功
                final_url = page.url
                if any(p in final_url for p in ["cgi-bin/home", "cgi-bin/frame", "loginpage"]):
                    # 确保到达后台首页
                    if "cgi-bin/home" not in final_url and "cgi-bin/frame" not in final_url:
                        try:
                            await page.goto("https://mp.weixin.qq.com/cgi-bin/home?action=home", timeout=15000)
                            await page.wait_for_timeout(2000)
                        except Exception:
                            pass

                    token = await _get_token(page)
                    await _save_cookies(context)
                    await browser.close()
                    await p.stop()
                    return {"success": True, "token": token}
                else:
                    await browser.close()
                    await p.stop()
                    return {"success": False}

            result = run_async(do_login_with_qr())

            if result["success"]:
                st.session_state.logged_in = True
                st.session_state.token = result["token"]
                qr_placeholder.empty()
                status_placeholder.empty()
                st.success("✅ 登录成功！")
                st.rerun()
            else:
                qr_placeholder.empty()
                status_placeholder.empty()
                st.error("❌ 登录超时（2分钟），请重新点击按钮获取二维码")

        except Exception as e:
            st.error(f"❌ 登录失败: {e}")


# ──────────────────────────────────────────────
# Step 3: 采集文章列表
# ──────────────────────────────────────────────

st.header("③ 采集文章列表")

if not st.session_state.logged_in:
    st.info("请先完成登录")
elif not st.session_state.biz:
    st.info("请先输入文章链接")
else:
    from datetime import date

    biz = st.session_state.biz
    existing_count = get_article_count(biz)

    if existing_count > 0:
        st.success(f"📊 已采集到 **{existing_count}** 篇文章，可在下方筛选和导出")

    st.markdown("---")

    # --- 采集模式选择 ---
    crawl_mode = st.radio("采集方式", ["全部", "最近 N 篇", "按发布日期范围"], horizontal=True, key="crawl_mode")

    crawl_max_count = None  # None = 全部

    if crawl_mode == "最近 N 篇":
        crawl_max_count = st.number_input("采集最近多少篇", min_value=1, max_value=10000, value=20, step=5, key="crawl_n")

    crawl_start_date = None
    crawl_end_date = None
    if crawl_mode == "按发布日期范围":
        col_s, col_e = st.columns(2)
        with col_s:
            crawl_start_date = st.date_input("发布开始日期", value=date(2024, 1, 1), key="crawl_start")
        with col_e:
            crawl_end_date = st.date_input("发布结束日期", value=date.today(), key="crawl_end")

    # 采集按钮
    btn_label = "📥 开始采集"
    if crawl_mode == "最近 N 篇":
        btn_label = f"📥 采集最近 {crawl_max_count} 篇"
    elif crawl_mode == "按发布日期范围":
        btn_label = f"📥 采集 {crawl_start_date} ~ {crawl_end_date} 的文章"

    if st.button(btn_label, disabled=st.session_state.crawl_running, type="primary"):
        st.session_state.crawl_running = True
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            async def do_crawl():
                from playwright.async_api import async_playwright
                from core.crawler import (
                    login_and_get_context, _get_token,
                    _search_biz_and_get_fakeid, crawl_all_articles,
                )

                p = await async_playwright().start()
                browser, context, page = await login_and_get_context(p, headless=True)

                token = await _get_token(page)
                if not token:
                    token = st.session_state.token

                _biz = st.session_state.biz
                _nickname = st.session_state.nickname
                status_text.text("正在搜索公众号信息...")

                if not _nickname:
                    await browser.close()
                    await p.stop()
                    return {"success": False, "error": "未获取到公众号名称，请确认第①步已正确识别公众号"}

                biz_info = await _search_biz_and_get_fakeid(page, token, nickname=_nickname, biz=_biz)

                if not biz_info:
                    await browser.close()
                    await p.stop()
                    return {"success": False, "error": f"在公众平台中未搜索到「{_nickname}」，请检查公众号名称"}

                fakeid = biz_info["fakeid"]
                nickname = biz_info["nickname"]

                upsert_account(_biz, nickname, biz_info.get("round_head_img"))
                st.session_state.nickname = nickname
                st.session_state.fakeid = fakeid

                status_text.text(f"找到公众号: {nickname}，开始采集...")

                def on_progress(current, total):
                    if total > 0:
                        progress_bar.progress(current / total)
                    status_text.text(f"已采集 {current}/{total} 篇...")

                articles = await crawl_all_articles(
                    page, token, fakeid, _biz,
                    max_count=crawl_max_count,
                    progress_callback=on_progress,
                    start_date=crawl_start_date.strftime("%Y-%m-%d") if crawl_start_date else None,
                    end_date=crawl_end_date.strftime("%Y-%m-%d") if crawl_end_date else None,
                )

                await browser.close()
                await p.stop()
                return {"success": True, "count": len(articles), "nickname": nickname}

            result = run_async(do_crawl())

            if result["success"]:
                st.session_state.articles_fetched = True
                progress_bar.progress(1.0)
                status_text.text("")
                st.success(f"✅ 采集完成！共 {result['count']} 篇")
                st.rerun()
            else:
                st.error(f"❌ {result['error']}")

        except Exception as e:
            st.error(f"❌ 采集失败: {e}")
        finally:
            st.session_state.crawl_running = False

    # ──────────────────────────────────────────
    # 文章列表展示
    # ──────────────────────────────────────────

    all_articles = get_articles(biz)

    if all_articles:
        import pandas as pd

        st.markdown("---")

        # 标题搜索
        search_term = st.text_input("🔍 搜索标题关键词", "", key="search_articles")
        filtered = all_articles
        if search_term:
            filtered = [a for a in filtered if search_term.lower() in a.get("title", "").lower()]

        st.subheader(f"文章列表（{len(filtered)} 篇）")

        if not filtered:
            st.warning("当前条件下没有文章")
        else:
            # 全选/取消按钮
            col_sel1, col_sel2, _ = st.columns([1, 1, 4])
            with col_sel1:
                select_all = st.button("全选")
            with col_sel2:
                deselect_all = st.button("取消全选")

            # 处理全选/取消状态
            if "select_all_state" not in st.session_state:
                st.session_state.select_all_state = None
            if select_all:
                st.session_state.select_all_state = True
            if deselect_all:
                st.session_state.select_all_state = False

            # 构建表格数据
            df_data = []
            for idx, a in enumerate(filtered):
                # 默认勾选状态
                if st.session_state.select_all_state is True:
                    checked = True
                elif st.session_state.select_all_state is False:
                    checked = False
                else:
                    checked = not bool(a.get("pdf_path"))  # 默认勾选未导出的

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

            # 统计勾选
            selected_mask = edited_df["选择"].tolist()
            selected_articles = [filtered[i] for i, sel in enumerate(selected_mask) if sel]

            st.info(f"已勾选 **{len(selected_articles)}** 篇文章")

            st.session_state.selected_articles = selected_articles

            # ──────────────────────────────────────
            # Step 4: 确认导出 PDF
            # ──────────────────────────────────────

            st.header("④ 导出 PDF")

            default_dir = os.path.join(OUTPUT_DIR, st.session_state.nickname or biz)
            save_path = st.text_input(
                "📁 PDF 保存路径",
                value=default_dir,
                help="文件将保存到该目录下，可修改为任意本地路径",
            )

            if not selected_articles:
                st.warning("请先在上方列表中勾选要导出的文章")
            else:
                st.markdown(f"将导出 **{len(selected_articles)}** 篇文章为 PDF，保存到：`{save_path}`")

                if st.button("📄 确认导出 PDF", disabled=st.session_state.export_running, type="primary"):
                    st.session_state.export_running = True
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    try:
                        async def do_export():
                            from playwright.async_api import async_playwright
                            from core.pdf_exporter import export_articles_to_pdf
                            from core.crawler import login_and_get_context

                            p = await async_playwright().start()
                            browser, context, page = await login_and_get_context(p, headless=True)

                            def on_progress(current, total, title):
                                if total > 0:
                                    progress_bar.progress(current / total)
                                status_text.text(f"[{current}/{total}] 正在导出: {title}")

                            results = await export_articles_to_pdf(
                                context, selected_articles, biz,
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
    **使用步骤：**
    1. 粘贴目标公众号的任意一篇文章链接
    2. 扫码登录微信公众平台
    3. 点击「采集文章列表」获取全部文章
    4. 通过日期/篇数/关键词筛选文章
    5. 在列表中勾选要导出的文章
    6. 设置保存路径，确认导出 PDF

    **注意事项：**
    - 登录需要你拥有任意一个微信公众号
    - 采集速度受微信限制，约 2-5 秒/页
    - PDF 导出逐篇渲染，速度较慢
    """)

    st.divider()

    st.header("⚙️ 状态")
    st.write(f"登录状态: {'✅ 已登录' if st.session_state.logged_in else '❌ 未登录'}")
    st.write(f"公众号: {st.session_state.nickname or '未识别'}")
    st.write(f"输出目录: `{OUTPUT_DIR}`")
