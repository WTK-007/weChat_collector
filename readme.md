# 微信公众号文章提取器

输入任意一篇公众号文章链接，自动识别该公众号，批量获取所有文章并导出为 PDF。

## 功能

- 自动解析公众号文章链接，识别公众号
- 登录微信公众平台后台，获取完整文章列表
- 批量将文章导出为高质量 PDF（保留原始排版）
- 支持指定导出数量
- Streamlit 可视化操作界面
- SQLite 本地存储，避免重复抓取

## 安装

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

## 使用

```bash
streamlit run app.py
```

浏览器会自动打开操作界面，按页面步骤操作：

1. **输入链接** — 粘贴目标公众号的任意一篇文章链接
2. **扫码登录** — 点击登录按钮，用微信扫码登录公众平台后台
3. **获取列表** — 设置数量后点击获取，自动分页爬取文章列表
4. **导出 PDF** — 选择导出数量，批量导出为 PDF 文件

## 注意事项

- 登录公众平台需要你拥有任意一个微信公众号（订阅号/服务号均可）
- 文章抓取有频率限制，已内置随机延时（2-5 秒/页）
- PDF 文件保存在 `output/` 目录下，按公众号名称分文件夹
- Cookie 会保存在 `.cookies.json` 中供下次免登录使用

## 项目结构

```
GZH_articleGet/
├── app.py                 # Streamlit 主界面
├── config.py              # 项目配置
├── core/
│   ├── parser.py          # URL 解析
│   ├── crawler.py         # 文章列表爬取
│   ├── pdf_exporter.py    # PDF 导出
│   └── storage.py         # SQLite 存储
├── output/                # PDF 输出目录
├── requirements.txt
└── readme.md
```

## 技术栈

- **Python 3.11+**
- **Streamlit** — 可视化界面
- **Playwright** — 浏览器自动化（登录 + PDF 导出）
- **SQLite** — 本地数据存储
