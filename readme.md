# 微信公众号文章提取器

输入任意一篇公众号文章链接，自动识别该公众号，批量获取所有文章并导出为 PDF。

**无需登录微信公众平台，无需拥有公众号，任何人都能使用。**

## 功能特性

- **无需登录** — 通过文章页面直接采集，不需要公众号账号
- **智能识别** — 粘贴任意文章链接，自动解析公众号（支持长链接和短链接）
- **灵活采集** — 三种模式：全部文章 / 最近 N 篇 / 按发布日期范围筛选
- **高质量 PDF** — Playwright 渲染导出，保留原始排版，自动处理懒加载图片
- **去噪处理** — 导出时自动隐藏广告、评论区、二维码等非正文元素
- **本地存储** — SQLite 记录采集状态，避免重复抓取
- **可视化界面** — Streamlit 三步向导式操作

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 使用

```bash
streamlit run app.py
```

三步操作：

1. **粘贴链接** → 点击「识别公众号」
2. **选择采集方式** → 点击采集 → 在列表中勾选文章
3. **设置保存路径** → 点击「确认导出 PDF」

## 项目结构

```
GZH_articleGet/
├── app.py                 # Streamlit 主界面
├── config.py              # 配置
├── core/
│   ├── parser.py          # URL 解析
│   ├── crawler.py         # 文章列表采集（profile_ext 方案）
│   ├── pdf_exporter.py    # PDF 导出
│   └── storage.py         # SQLite 存储
├── output/                # PDF 输出目录
├── requirements.txt
└── readme.md
```

## 技术栈

- **Python 3.11+**
- **Streamlit** — Web 界面
- **Playwright** — 浏览器自动化（模拟微信内置浏览器）
- **SQLite** — 本地数据存储
