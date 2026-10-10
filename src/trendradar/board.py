from __future__ import annotations

import html
import sqlite3
from datetime import datetime

from .signals import signal_board


LABELS = {
    "NEW": "首次出现",
    "RISING": "持续升温",
    "TRACKING": "持续跟踪",
}


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _delta(signal: dict) -> str:
    bits: list[str] = []
    rank_delta = int(signal.get("rank_delta") or 0)
    score_delta = float(signal.get("score_delta") or 0)
    source_delta = int(signal.get("source_delta") or 0)
    if rank_delta:
        bits.append(f"排名 {'↑' if rank_delta > 0 else '↓'}{abs(rank_delta)}")
    if score_delta:
        bits.append(f"内容分 {score_delta:+g}")
    if source_delta:
        bits.append(f"独立来源 {source_delta:+d}")
    if not bits:
        bits.append(f"连续进入候选池 {int(signal.get('history_count') or 0)} 轮")
    return " · ".join(bits)


def _card(item: dict, index: int) -> str:
    signal = item.get("signal") or {}
    status = str(signal.get("status") or "TRACKING")
    badge = LABELS.get(status, "持续跟踪")
    action = _esc(item.get("action") or "TRACK")
    title = _esc(item.get("title") or "未命名信号")
    summary = _esc(item.get("event_summary") or item.get("what_changed") or "等待认知层补充")
    profit = _esc(item.get("profit_pool") or item.get("why_now") or "等待商业含义判断")
    delta = _esc(_delta(signal))
    rank = signal.get("content_rank") or index + 1
    sources = signal.get("source_count") or 0
    return f"""
    <article class="focus-card status-{status.lower()}">
      <div class="topline"><span class="rank">#{_esc(rank)}</span><span class="badge">{badge}</span><span class="action">{action}</span></div>
      <h2>{title}</h2>
      <p class="summary">{summary}</p>
      <div class="meaning"><span>商业含义</span><p>{profit}</p></div>
      <div class="meta"><span>{delta}</span><span>{_esc(sources)} 个独立来源</span></div>
    </article>
    """


def render_signal_board(conn: sqlite3.Connection, limit: int = 12) -> str:
    data = signal_board(conn, limit)
    items = data.get("items") or []
    summary = data.get("summary") or {}
    mode = data.get("ranking_mode") or "RULE"
    run_at = data.get("run_at") or "尚未运行"
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    top = "".join(_card(item, index) for index, item in enumerate(items[:3]))
    rows = []
    for item in items[3:]:
        signal = item.get("signal") or {}
        status = str(signal.get("status") or "TRACKING")
        rows.append(
            f"""
            <div class="signal-row status-{status.lower()}">
              <div class="row-main"><span class="badge">{LABELS.get(status,'持续跟踪')}</span><strong>{_esc(item.get('title'))}</strong></div>
              <div class="row-meta"><span>{_esc(_delta(signal))}</span><span>来源 {_esc(signal.get('source_count') or 0)}</span></div>
            </div>
            """
        )
    rest = "".join(rows) or '<div class="empty">暂无更多信号。</div>'
    empty_top = top or '<div class="empty">运行一次 daily 后，这里会显示当天最值得看的商业信号。</div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta http-equiv="refresh" content="300" />
<title>TrendRadar · 每日商业信号</title>
<style>
:root{{--bg:#f5f4ef;--panel:#fff;--ink:#171714;--muted:#6d6b62;--line:#e5e2d8;--green:#166534;--green-bg:#ecfdf3;--amber:#9a5b00;--amber-bg:#fff7df;--blue:#314a72;--shadow:0 18px 45px rgba(35,32,22,.08)}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
.shell{{max-width:1240px;margin:0 auto;padding:38px 28px 56px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:24px}}
.eyebrow{{font-size:12px;letter-spacing:.18em;color:var(--muted);font-weight:700}} h1{{font-size:34px;margin:8px 0 6px;letter-spacing:-.03em}} header p{{margin:0;color:var(--muted)}}
.run{{font-size:12px;color:var(--muted);text-align:right;line-height:1.8}} .stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0 24px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;box-shadow:var(--shadow)}} .stat b{{display:block;font-size:30px;margin-top:5px}} .stat span{{font-size:13px;color:var(--muted)}}
.focus-grid{{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:14px;margin-bottom:30px}} .focus-card{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:var(--shadow);min-height:280px}}
.focus-card:first-child{{min-height:340px}} .topline{{display:flex;align-items:center;gap:8px;margin-bottom:16px}} .rank{{font-size:12px;color:var(--muted)}} .badge,.action{{display:inline-flex;padding:5px 9px;border-radius:999px;font-size:12px;background:#f2f1ec;color:#4d4b43}}
.status-new .badge{{background:var(--green-bg);color:var(--green)}} .status-rising .badge{{background:var(--amber-bg);color:var(--amber)}} .focus-card h2{{font-size:22px;line-height:1.35;margin:0 0 12px}} .focus-card:first-child h2{{font-size:28px}}
.summary{{color:#4f4d45;line-height:1.65;min-height:54px}} .meaning{{border-top:1px solid var(--line);margin-top:18px;padding-top:16px}} .meaning span{{font-size:12px;color:var(--muted)}} .meaning p{{margin:7px 0;line-height:1.55}}
.meta{{display:flex;justify-content:space-between;gap:12px;color:var(--muted);font-size:12px;margin-top:18px}} section h3{{font-size:18px;margin:0 0 12px}} .list{{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:var(--shadow)}}
.signal-row{{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:center}} .signal-row:last-child{{border-bottom:0}} .row-main{{display:flex;align-items:center;gap:10px;min-width:0}} .row-main strong{{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.row-meta{{display:flex;gap:18px;color:var(--muted);font-size:12px;white-space:nowrap}} .empty{{background:var(--panel);border:1px dashed var(--line);border-radius:16px;padding:28px;color:var(--muted)}} footer{{margin-top:28px;color:var(--muted);font-size:12px;text-align:center}}
@media(max-width:900px){{.focus-grid{{grid-template-columns:1fr}}.focus-card,.focus-card:first-child{{min-height:auto}}.stats{{grid-template-columns:1fr 1fr 1fr}}header{{align-items:flex-start;flex-direction:column}}.run{{text-align:left}}}}
@media(max-width:640px){{.shell{{padding:24px 16px 40px}}h1{{font-size:28px}}.stats{{grid-template-columns:1fr}}.signal-row{{align-items:flex-start;flex-direction:column}}.row-meta{{white-space:normal;flex-wrap:wrap}}}}
</style>
</head>
<body>
<main class="shell">
<header><div><div class="eyebrow">TRENDRADAR · BUSINESS SIGNALS</div><h1>每日商业信号看板</h1><p>先看新出现什么、什么正在升温，再决定今天真正值得研究的 1–3 件事。</p></div><div class="run">Ranking: {_esc(mode)}<br/>数据轮次: {_esc(run_at)}<br/>页面生成: {_esc(generated)}</div></header>
<div class="stats"><div class="stat"><span>首次出现</span><b>{int(summary.get('NEW') or 0)}</b></div><div class="stat"><span>持续升温</span><b>{int(summary.get('RISING') or 0)}</b></div><div class="stat"><span>持续跟踪</span><b>{int(summary.get('TRACKING') or 0)}</b></div></div>
<div class="focus-grid">{empty_top}</div>
<section><h3>其余值得跟踪的信号</h3><div class="list">{rest}</div></section>
<footer>TrendRadar · 自动刷新 5 分钟 · 信号状态只做诊断，不替代证据门槛与人工判断</footer>
</main>
</body>
</html>"""
