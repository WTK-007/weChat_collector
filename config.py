"""项目配置"""

import os

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# 爬虫配置
CRAWL_DELAY_MIN = 2  # 最小请求间隔（秒）
CRAWL_DELAY_MAX = 5  # 最大请求间隔（秒）
PAGE_SIZE = 10  # 每页文章数

# 微信公众平台地址
MP_BASE_URL = "https://mp.weixin.qq.com"
MP_LOGIN_URL = "https://mp.weixin.qq.com/"
MP_ARTICLE_LIST_API = "https://mp.weixin.qq.com/cgi-bin/appmsg"

# PDF 导出配置
PDF_OPTIONS = {
    "format": "A4",
    "print_background": True,
    "margin": {
        "top": "10mm",
        "bottom": "10mm",
        "left": "10mm",
        "right": "10mm",
    },
}
