"""
Tweet Growth Tracker — 配置中心
所有阈值、权重、路径在这里统一管理
"""

import os
from pathlib import Path

# ─── 数据存储 ─────────────────────────────────────────────────────────────────
# 优先读环境变量，方便本地/VPS/skill 三个场景共用
DATA_FILE = Path(os.environ.get(
    "TWEET_GROWTH_DATA",
    Path.home() / ".tweet-growth" / "data.json"
))

DISCOVER_CACHE = Path(os.environ.get(
    "TWEET_GROWTH_DISCOVER_CACHE",
    Path.home() / ".tweet-growth" / "discover_cache.json"
))

# ─── 采样频率 ─────────────────────────────────────────────────────────────────
NEW_TWEET_HOURS   = 48    # 新推文定义：发出后多少小时内算"新"
FAST_INTERVAL_MIN = 15    # 新推文：每15分钟采一次
NORM_INTERVAL_MIN = 60    # 老推文：每小时采一次

# ─── ETCH 导数检测（全部归一化到 per-hour）────────────────────────────────────
ETCH_WINDOW_SIZE    = 5     # 滑窗大小（样本数）
ETCH_SPIKE_RATE     = 0.30  # 每小时增速超过基线 30% 触发候选
ETCH_CONFIRM_COUNT  = 3     # 连续3个窗口确认才算爆点
ETCH_SURGE_OVERRIDE = 1.0   # 单窗口增速超过 100%/h 直接确认

# ─── 饱和检测 ─────────────────────────────────────────────────────────────────
SATURATION_WINDOW    = 6    # 连续几个样本
SATURATION_THRESHOLD = 0.02 # 每小时增速 < 2% 视为长尾

# ─── 多信号权重 ───────────────────────────────────────────────────────────────
WEIGHT_VIEWS     = 1.0
WEIGHT_LIKES     = 1.0
WEIGHT_BOOKMARKS = 1.5
WEIGHT_RETWEETS  = 3.0
WEIGHT_REPLIES   = 0.5

# ─── 传播模式阈值 ─────────────────────────────────────────────────────────────
# RT/千次浏览 的比值，用于区分传播类型
INFLUENCER_RT_RATIO = 2.0   # ‰ 以上 → 大号转发驱动
ALGORITHM_RT_RATIO  = 0.5   # ‰ 以下 → 算法推荐驱动

# ─── 话题交叉分析 ─────────────────────────────────────────────────────────────
CROSS_SEARCH_RESULTS = 8    # 每个关键词搜几条
CROSS_TIME_WINDOW_H  = 24   # 爆点前后多少小时内算"同时段"
