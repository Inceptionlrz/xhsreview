"""
主题样式常量 - 暗色主题（仿 Linux.do 风格）
"""

# ================== 颜色系统 ==================
COLORS = {
    "bg_root":        "#2B2B33",
    "bg_panel":       "#23232A",
    "bg_section":     "#1C1C22",
    "bg_input":       "#15151A",
    "bg_log":         "#1A1A20",
    "bg_canvas":      "#2B2B33",

    "fg_text":        "#D6D6DC",
    "fg_sub":         "#9A9AA2",
    "fg_title":       "#FFFFFF",
    "fg_value":       "#FF7043",
    "fg_link":        "#7BB3F0",
    "fg_ok":          "#67C97A",
    "fg_warn":        "#F0B45A",
    "fg_err":         "#E25C5C",
    "fg_section":     "#7BC1F5",

    "btn_bg":         "#3A3A44",
    "btn_fg":         "#FFFFFF",
    "btn_start":      "#2D6CDF",
    "btn_stop":       "#E25C5C",
    "btn_hover":      "#494953",
    # 按压态：比 btn_bg 更深，模拟 scale(0.97) 的视觉收缩感
    # 参考 emil-design-eng: buttons must feel responsive (100-160ms)
    "btn_pressed":    "#2E2E36",
    "btn_start_pressed": "#2455B0",
    "btn_stop_pressed":  "#B04848",

    # 强调色：用于焦点、链接、活跃指示
    "accent":         "#5AA9F0",
    "accent_dim":     "#3D7FBF",

    # 弹窗阴影色（模拟 depth，apple §12 Materials）
    "shadow":         "#0D0D11",

    "border":         "#3A3A44",
    "border_focus":   "#5AA9F0",
    "select_bg":      "#3F4A6B",
}

# ================== 字体 ==================
FONTS = {
    "title":   ("Microsoft YaHei UI", 11, "bold"),
    "section": ("Microsoft YaHei UI", 10, "bold"),
    "normal":  ("Microsoft YaHei UI", 9),
    "small":   ("Microsoft YaHei UI", 8),
    "value":   ("Consolas", 10, "bold"),
    "log":     ("Consolas", 9),
    "label":   ("Microsoft YaHei UI", 9, "bold"),
}

# ================== 尺寸 ==================
SIZE = {
    "win_w":  900,
    "win_h":  1010,
    "pad":    8,
    "panel_pad": 10,
    "row_h":  28,
    "log_h":  8,
    "log_w":  60,
}

# ================== 小红书真实板块（首页频道栏） ==================
DEFAULT_CATEGORIES = [
    ("推荐",      True),
    ("世界杯",    False),
    ("穿搭",      True),
    ("美食",      True),
    ("彩妆",      True),
    ("影视",      False),
    ("职场",      False),
    ("情感",      False),
    ("家居",      False),
    ("游戏",      False),
    ("旅行",      False),
    ("健身",      False),
    ("视频",      False),
]

# 板块过滤（按帖子标题/作者做关键词匹配；宽松策略）
CATEGORY_KEYWORDS = {
    "推荐":      [],
    "世界杯":    ["世界杯", "足球", "梅西", "C罗", "阿根廷", "巴西", "决赛", "世界杯"],
    "穿搭":      ["穿搭", "搭配", "look", "OOTD", "时装", "衣服", "裙子", "外套"],
    "美食":      ["美食", "吃", "餐厅", "探店", "菜谱", "小吃", "必吃榜", "味道"],
    "彩妆":      ["彩妆", "化妆", "口红", "粉底", "眼影", "美妆", "化妆师"],
    "影视":      ["电影", "电视剧", "综艺", "演员", "剧情", "票房", "剧"],
    "职场":      ["职场", "工作", "老板", "同事", "简历", "面试", "加班", "公司"],
    "情感":      ["情感", "爱情", "恋爱", "男朋友", "女朋友", "分手", "相亲"],
    "家居":      ["家居", "装修", "家具", "收纳", "客厅", "卧室", "房子", "家电"],
    "游戏":      ["游戏", "王者", "原神", "LOL", "Steam", "PS5", "Switch", "开黑"],
    "旅行":      ["旅行", "旅游", "攻略", "景点", "民宿", "酒店", "机票", "自驾"],
    "健身":      ["健身", "减肥", "瑜伽", "跑步", "马甲线", "瘦身", "撸铁", "减脂"],
    "视频":      ["视频", "vlog", "直播", "短视频", "搞笑视频"],
}
