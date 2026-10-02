"""中文社媒热榜聚合：微博 / 抖音 / 知乎 / 头条 / 小红书 / 百度 / B站.

数据源方案移植自 ZJU-REAL/Easel（Apache-2.0）`skills/shared/hotlist-apis.md`：
主源 60s API（https://60s.viki.moe/v2/*），失败时按板块降级到 xxapi
（https://v2.xxapi.cn/api/*）。两者均为免费公益接口、无需密钥；
每日流水线拉取一次即可，请勿高频调用。

作为 ``kind: story`` 信源接入：每条热搜成为一条 story 信号，走简报的
story_assessment（值得写 / 切口）管道，而不是痛点分类。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import quote

import httpx

from ..core.errors import SourceError
from ..core.timeutil import utcnow
from .base import AdapterHealth, BaseAdapter, Engagement, FetchResult, RawSignal, SearchQuery
from .http import client, get_json

SIXTY_S_BASE = "https://60s.viki.moe/v2/"
XXAPI_BASE = "https://v2.xxapi.cn/api/"

#: board id -> (60s 路径, 中文名)
BOARDS: dict[str, tuple[str, str]] = {
    "weibo": ("weibo", "微博热搜"),
    "douyin": ("douyin", "抖音热搜"),
    "zhihu": ("zhihu", "知乎热榜"),
    "toutiao": ("toutiao", "头条热榜"),
    "rednote": ("rednote", "小红书热搜"),
    "baidu": ("baidu/hot", "百度热搜"),
    "bili": ("bili", "B站热门"),
}

#: 60s 失败时的 xxapi 备用端点（仅部分板块有）
XXAPI_FALLBACK: dict[str, str] = {
    "weibo": "weibohot",
    "douyin": "douyinhot",
    "baidu": "baiduhot",
    "bili": "bilibilihot",
}

#: 条目缺 url 时回退到平台搜索页
SEARCH_URLS: dict[str, str] = {
    "weibo": "https://s.weibo.com/weibo?q={q}",
    "douyin": "https://www.douyin.com/search/{q}",
    "zhihu": "https://www.zhihu.com/search?type=content&q={q}",
    "toutiao": "https://so.toutiao.com/search?keyword={q}",
    "rednote": "https://www.xiaohongshu.com/search_result?keyword={q}",
    "baidu": "https://www.baidu.com/s?wd={q}",
    "bili": "https://search.bilibili.com/all?keyword={q}",
}

DEFAULT_BOARDS = ["weibo", "douyin", "zhihu", "toutiao", "rednote", "baidu"]


def parse_rows(payload: object) -> list[dict]:
    """60s v2 / xxapi 的 data 可能是数组或嵌套 ``{data:{data:[...]}}``；其余形状返回 []."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


class HotlistAdapter(BaseAdapter):
    adapter_id = "hotlist"
    type = "story"

    @property
    def boards(self) -> list[str]:
        wanted = self.config.extra.get("boards") or DEFAULT_BOARDS
        return [b for b in wanted if b in BOARDS]

    @property
    def per_board(self) -> int:
        try:
            return max(1, min(50, int(self.config.extra.get("per_board", 10))))
        except (TypeError, ValueError):
            return 10

    def fetch_latest(self) -> FetchResult:
        result = FetchResult()
        fetched_at = utcnow()
        with client() as c:
            for board in self.boards:
                if len(result.signals) >= self.config.max_per_round:
                    break
                try:
                    rows, provider = self._fetch_board(c, board)
                except SourceError as exc:
                    result.warnings.append(f"{self.id}: {board} unavailable ({exc})")
                    continue
                for rank, row in enumerate(rows[: self.per_board], start=1):
                    signal = self._to_signal(board, rank, row, provider, fetched_at)
                    if signal is not None:
                        result.signals.append(signal)
                    if len(result.signals) >= self.config.max_per_round:
                        break
        return result

    def _fetch_board(self, c: httpx.Client, board: str) -> tuple[list[dict], str]:
        path, _ = BOARDS[board]
        try:
            rows = parse_rows(get_json(c, SIXTY_S_BASE + path, attempts=2))
            if rows:
                return rows, "60s"
            last = "60s: empty response"
        except SourceError as exc:
            last = str(exc)
        endpoint = XXAPI_FALLBACK.get(board)
        if endpoint:
            rows = parse_rows(get_json(c, XXAPI_BASE + endpoint, attempts=2))
            if rows:
                return rows, "xxapi"
            last = f"{last}; xxapi: empty response"
        raise SourceError(last)

    def _to_signal(
        self, board: str, rank: int, row: dict, provider: str, fetched_at: datetime
    ) -> RawSignal | None:
        title = str(row.get("title") or row.get("name") or row.get("word") or "").strip()
        if not title:
            return None
        _, board_name = BOARDS[board]
        url = str(row.get("url") or row.get("link") or row.get("mobile_url") or "").strip()
        if not url.startswith("http"):
            url = SEARCH_URLS[board].format(q=quote(title))
        hot_raw = row.get("hot") or row.get("hot_value") or row.get("views") or 0
        try:
            hot = max(0, int(float(hot_raw)))
        except (TypeError, ValueError):
            hot = 0
        digest = hashlib.sha1(f"{board}:{title}".encode()).hexdigest()[:16]
        summary = str(row.get("desc") or row.get("description") or "").strip()
        content = f"{board_name}第{rank}名：{title}" + (f"。{summary}" if summary else "")
        return RawSignal(
            external_id=f"hotlist:{board}:{digest}",
            source=self.id,
            adapter=self.adapter_id,
            source_type=self.type,
            url=url,
            title=title,
            content=content[:6000],
            created_at=fetched_at,
            fetched_at=fetched_at,
            engagement=Engagement(votes=hot),
            metadata={
                "board": board,
                "board_name": board_name,
                "rank": rank,
                "hot": hot,
                "provider": provider,
            },
        )

    def search(self, query: SearchQuery) -> FetchResult:
        needle = query.text.lower()
        latest = self.fetch_latest()
        latest.signals = [s for s in latest.signals if needle in f"{s.title} {s.content}".lower()][
            : query.limit
        ]
        return latest

    def health(self) -> AdapterHealth:
        return AdapterHealth(ok=True, mode=self.mode, detail="60s → xxapi 公益接口，保持低频调用")
