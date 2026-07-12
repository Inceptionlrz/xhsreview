"""
小红书搜索筛选模块
==============
提供与网页端「筛选」面板对应的选项配置，以及把中文选项映射到 URL / API 参数的
方法。后续可以扩展为在真实浏览器中点击筛选面板，但当前先通过 URL 参数传递，
让爬虫在搜索时带上排序、笔记类型、发布时间等条件。
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Any
from urllib.parse import urlencode


# ---------- 选项定义（中文显示值 → 内部/URL 参数值）----------
SORT_OPTIONS: List[Tuple[str, str]] = [
    ("综合", ""),
    ("最新", "time_descending"),
    ("最多点赞", "popularity_descending"),
    ("最多评论", "comment_descending"),
    ("最多收藏", "collect_descending"),
]

NOTE_TYPE_OPTIONS: List[Tuple[str, str]] = [
    ("不限", ""),
    ("视频", "video-note"),
    ("图文", "image-text-note"),
]

PUBLISH_TIME_OPTIONS: List[Tuple[str, str]] = [
    ("不限", ""),
    ("一天内", "ONE_DAY"),
    ("一周内", "ONE_WEEK"),
    ("半年内", "HALF_YEAR"),
]

SEARCH_SCOPE_OPTIONS: List[Tuple[str, str]] = [
    ("不限", ""),
    ("已看过", "viewed"),
    ("未看过", "unviewed"),
    ("已关注", "followed"),
]

LOCATION_OPTIONS: List[Tuple[str, str]] = [
    ("不限", ""),
    ("同城", "same_city"),
    ("附近", "nearby"),
]

# 有序分类列表，方便 UI 遍历渲染
# (字段名, 分类中文名, 选项列表)
FILTER_CATEGORIES: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    ("sort_by", "排序依据", SORT_OPTIONS),
    ("note_type", "笔记类型", NOTE_TYPE_OPTIONS),
    ("publish_time", "发布时间", PUBLISH_TIME_OPTIONS),
    ("search_scope", "搜索范围", SEARCH_SCOPE_OPTIONS),
    ("location", "位置距离", LOCATION_OPTIONS),
]

# 字段名 -> URL 参数名
URL_PARAM_NAMES: Dict[str, str] = {
    "sort_by": "sort",
    "note_type": "note_type",
    "publish_time": "note_time",
    "search_scope": "search_scope",
    "location": "location",
}


@dataclass
class SearchFilters:
    """用户在小红书搜索面板上的筛选条件。"""

    sort_by: str = "综合"
    note_type: str = "不限"
    publish_time: str = "不限"
    search_scope: str = "不限"
    location: str = "不限"

    def __post_init__(self):
        """防御性：如果传入非法值，回退到第一个选项。"""
        for key, _, options in FILTER_CATEGORIES:
            valid = {opt[0] for opt in options}
            val = getattr(self, key)
            if val not in valid:
                setattr(self, key, options[0][0])

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SearchFilters":
        return cls(
            sort_by=d.get("sort_by", "综合"),
            note_type=d.get("note_type", "不限"),
            publish_time=d.get("publish_time", "不限"),
            search_scope=d.get("search_scope", "不限"),
            location=d.get("location", "不限"),
        )

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def selected_params(self) -> Dict[str, str]:
        """返回非默认（非空内部值）的筛选参数，用于 URL 查询。"""
        params: Dict[str, str] = {}
        for key, _, options in FILTER_CATEGORIES:
            val = getattr(self, key)
            inner = dict(options).get(val, "")
            if inner:
                params[URL_PARAM_NAMES[key]] = inner
        return params

    def build_search_url(self, keyword: str,
                         base: str = "https://www.xiaohongshu.com/search_result") -> str:
        """根据关键词和筛选条件构造搜索 URL。"""
        query: Dict[str, str] = {
            "keyword": (keyword or "").strip(),
            "source": "web_explore_feed",
        }
        query.update(self.selected_params())
        return f"{base}?{urlencode(query)}"

    def apply_to_posts(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """在本地对已有的帖子列表做二次过滤（主要用于 Mock / 兜底场景）。

        支持的字段：
        - type: "video" | "normal" 等，用于笔记类型过滤
        - publish_time: 字符串，如 "1天前" / "一周前" 等，用于发布时间过滤
        - liked_count: 数字或字符串，用于排序
        - comment_count: 数字或字符串，用于排序
        """
        out = list(posts)

        # 笔记类型
        if self.note_type != "不限":
            mapped = {"视频": "video", "图文": "normal"}
            wanted = mapped.get(self.note_type)
            if wanted:
                out = [p for p in out if (p.get("type") or "").lower() == wanted]

        # 发布时间（简单字符串匹配）
        if self.publish_time != "不限":
            mapped = {"一天内": "天前", "一周内": "周前", "半年内": "月前"}
            wanted = mapped.get(self.publish_time)
            if wanted:
                out = [p for p in out if wanted in (p.get("publish_time") or "")]

        # 排序（仅在模拟数据带数字字段时生效）
        sort_key = None
        if self.sort_by == "最多点赞":
            sort_key = "liked_count"
        elif self.sort_by == "最多评论":
            sort_key = "comment_count"
        elif self.sort_by == "最多收藏":
            sort_key = "collected_count"
        elif self.sort_by == "最新":
            sort_key = "publish_time"

        if sort_key:
            def _num(p):
                try:
                    return int(str(p.get(sort_key, "0")).replace("+", "").replace("万", "0000"))
                except Exception:
                    return 0
            out.sort(key=_num, reverse=True)

        return out


# 兼容旧字典的辅助函数
def normalize_filters(obj: Any) -> Dict[str, str]:
    """把任意对象转成 SearchFilters 能识别的字典。"""
    if isinstance(obj, SearchFilters):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: str(v) for k, v in obj.items() if k in {
            "sort_by", "note_type", "publish_time", "search_scope", "location"
        }}
    return {}
