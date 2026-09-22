from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .pipeline import today
from .trends import latest_world_model_update


def write_daily_brief(conn, output_dir: str | Path, timezone_name: str = "Asia/Shanghai") -> Path:
    now = datetime.now(ZoneInfo(timezone_name))
    items = today(conn, 5)
    world = latest_world_model_update(conn)
    lines = [
        f"# 今日商业趋势认知简报｜{now:%Y-%m-%d}",
        "",
        f"今天优中选优保留 {len(items)} 条。",
        "",
    ]
    for index,item in enumerate(items,1):
        lines.extend([
            f"## {index}. {item['title']}",
            "",
            f"**发生了什么：** {item.get('event_summary') or '待补充'}",
            "",
            f"**真正改变：** {item.get('what_changed') or '待认知分析'}",
            "",
            f"**为什么现在：** {item.get('why_now') or '待认知分析'}",
            "",
            f"**利润池：** {item.get('profit_pool') or '待判断'}",
            "",
            f"**谁受益：** {item.get('who_benefits') or '待判断'}",
            "",
            f"**谁受损：** {item.get('who_loses') or '待判断'}",
            "",
            f"**中国映射：** {item.get('china_mapping') or '待验证'}",
            "",
            f"**最强反方：** {item.get('strongest_counter') or '待补充'}",
            "",
            f"**建议：** {item.get('action')}",
            "",
        ])
    lines.append("## 今日世界模型更新")
    lines.append("")
    if world:
        lines.append(world.get("summary") or "已生成趋势更新。")
    else:
        lines.append("尚无足够趋势证据，暂不生成世界模型结论。")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{now:%Y-%m-%d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
