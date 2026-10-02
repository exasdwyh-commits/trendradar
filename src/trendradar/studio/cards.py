"""小红书知识卡导出：母稿 / 平台版本 → 自包含 HTML 卡片（3:4，1080×1440）.

借鉴 ZJU-REAL/Easel 知识卡的版式思路（大标题 + 要点列表 + 品牌页脚），但走
TrendRadar 的"不依赖外部资源"路线：纯内联样式单文件 HTML，无字体 / 脚本 /
图片外链，浏览器打开即是成品，截图或打印成图即可发小红书。

要点提取是确定性的：优先取正文里的列表项，不足时退回句子切分——不经过模型，
内容严格来自稿件本身，与"AI 只依据素材写"的原则一致。
"""

from __future__ import annotations

import html as html_lib
import re

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+(.+)$", re.M)
_INLINE_MD = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
]


def _clean_inline(text: str) -> str:
    for pattern, repl in _INLINE_MD:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


def extract_points(markdown: str, limit: int = 5) -> list[str]:
    """列表项优先；不足两条时退回句子切分。确定性，不调用模型。"""
    points = [_clean_inline(m.group(1)) for m in _BULLET_RE.finditer(markdown or "")]
    points = [p for p in points if len(p) >= 4]
    if len(points) < 2:
        from .publishing import markdown_to_plain

        plain = markdown_to_plain(markdown or "")
        sentences = [s.strip() for s in re.split(r"[。！？!?\n]+", plain)]
        points = [s for s in sentences if len(s) >= 8]
    return points[:limit]


def render_card_html(
    *,
    title: str,
    points: list[str],
    footer: str = "TrendRadar 写作台",
    accent: str = "#3b5bdb",
) -> str:
    esc = html_lib.escape
    items = "\n".join(
        '<li style="margin:0 0 30px;display:flex;align-items:flex-start;">'
        f'<span style="flex:none;width:14px;height:14px;margin:17px 18px 0 0;'
        f'border-radius:4px;background:{esc(accent)};"></span>'
        f'<span style="flex:1;">{esc(p)}</span></li>'
        for p in points
    ) or ('<li style="margin:0;color:#999;">（正文里还没有可提取的要点，先写几条列表或完整句子）</li>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{esc(title)} · 知识卡</title>
</head>
<body style="margin:0;padding:24px;background:#e8eaf0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
<section style="width:1080px;height:1440px;margin:0 auto;box-sizing:border-box;display:flex;flex-direction:column;background:linear-gradient(160deg,#ffffff 0%,#f4f6ff 100%);border-radius:28px;padding:88px 84px;overflow:hidden;">
  <div style="flex:none;">
    <div style="width:64px;height:10px;border-radius:5px;background:{esc(accent)};margin-bottom:36px;"></div>
    <h1 style="margin:0 0 56px;font-size:58px;line-height:1.35;font-weight:800;color:#15171f;letter-spacing:1px;">{esc(title)}</h1>
  </div>
  <ul style="flex:1;margin:0;padding:0;list-style:none;font-size:34px;line-height:1.6;color:#2c2f3a;">
{items}
  </ul>
  <div style="flex:none;display:flex;justify-content:space-between;align-items:center;border-top:2px solid #e3e6f2;padding-top:34px;font-size:26px;color:#8a8fa3;">
    <span>{esc(footer)}</span>
    <span style="color:{esc(accent)};font-weight:600;">◆</span>
  </div>
</section>
</body>
</html>
"""


def document_card_html(title: str, markdown: str) -> str:
    return render_card_html(title=title or "未命名稿件", points=extract_points(markdown))
