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

# 微信 WeChat 移动端 User-Agent（模拟微信内置浏览器）
WECHAT_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 MicroMessenger/8.0.38(0x18002630) "
    "NetType/WIFI Language/zh_CN"
)

# 微信公众号主页（历史消息页）
PROFILE_EXT_URL = (
    "https://mp.weixin.qq.com/mp/profile_ext?"
    "action=home&__biz={biz}&scene=124#wechat_redirect"
)

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
