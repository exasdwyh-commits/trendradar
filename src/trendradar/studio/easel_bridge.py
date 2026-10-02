"""Easel 发布桥接：把平台版本移交 ZJU-REAL/Easel 真实发布，并回收发布结果入账.

TrendRadar 坚持"不直连平台 API"；真实发布交给 Easel（OpenClaw Agent + 七平台
publisher 技能）。桥接协议是纯文件握手，不依赖 Easel 是否安装、不引入新服务：

    <outbox>/<package>/
        handoff.json   平台、标题、来源 id、内容哈希、状态（pending/recorded）
        content.md     正文 Markdown
        content.txt    纯文本（小红书 / X 等短内容平台直接可用）
        wechat.html    仅公众号：内联样式排版 HTML（粘贴即用）

Easel 侧（或任何自动化、甚至人工）发布完成后，把结果写回同目录 result.json::

    {"status": "published", "external_url": "https://…", "note": "可选备注"}

``sync_results()`` 扫描 outbox，把已发布的包记入发布账本并把 handoff 状态改为
recorded（幂等，重复 sync 不会重复记账）。outbox 默认 ``<data_dir>/easel_outbox``，
可用 .env 的 ``EASEL_OUTBOX`` 指到 Easel 的工作目录。协议详见 docs/EASEL_BRIDGE.md。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..core.errors import NotFound, ValidationFailed
from ..core.settings import get_settings
from .ai import PLATFORM_NAMES
from .documents import get_document, split_leading_h1
from .publishing import get_variant, markdown_to_plain, markdown_to_wechat_html, record_publication

HANDOFF_FILE = "handoff.json"
RESULT_FILE = "result.json"
PROTOCOL = "trendradar-easel-handoff/1"

#: TrendRadar 平台 → Easel publisher 技能名。
#:
#: 名字取自 Easel 仓库 `skills/openclaw/<dir>/SKILL.md` frontmatter 的 ``name``
#: （2026-10-01 对 main 分支逐条核对）。Easel CLI 的解析规则见
#: `easel/commands/skill.py`：先按字面找，找不到再加 ``skill-`` 前缀 —— 所以这里写规范全名。
#: **技能名写错不会报任何错**，只会让 Easel Agent 找不到技能、静默发不出去，
#: 由 `tests/test_easel_bridge.py::test_easel_publishers_are_real_easel_skills` 守住。
#:
#: 不在表里的平台（toutiao / x）Easel 没有对应 publisher，照样出包，由人工或其他自动化发布。
EASEL_PUBLISHERS: dict[str, str] = {
    "wechat": "skill-wechat-publisher",
    "xiaohongshu": "skill-xhs-publisher",
    "zhihu": "skill-zhihu-publisher",
}

_OK_STATUSES = {"published", "success", "ok"}


def outbox_dir() -> Path:
    """outbox 路径。**只计算，不创建** —— 读接口（bridge_status / list_packages）不该写盘。"""
    settings = get_settings()
    custom = (getattr(settings, "easel_outbox", "") or "").strip()
    return Path(custom) if custom else settings.root / settings.data_dir / "easel_outbox"


def _ensure_outbox_dir() -> Path:
    """真正要落包时才建目录。"""
    path = outbox_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_packages() -> list[dict]:
    """outbox 里的全部 handoff 包（新→旧）；损坏的 manifest 跳过而不是炸掉。"""
    root = outbox_dir()
    if not root.is_dir():  # 还没出过包：返回空，不顺手把目录建出来
        return []
    packages: list[dict] = []
    for pkg_dir in sorted(root.iterdir(), reverse=True):
        manifest_path = pkg_dir / HANDOFF_FILE
        if not pkg_dir.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        result = None
        result_path = pkg_dir / RESULT_FILE
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = {"status": "invalid", "error": "result.json 不是合法 JSON"}
        packages.append(
            {"package": pkg_dir.name, "path": str(pkg_dir), "handoff": manifest, "result": result}
        )
    return packages


def handoff(conn: sqlite3.Connection, document_id: str, *, variant_id: str | None = None) -> dict:
    """导出一份 handoff 包。对同稿件、同版本、同内容的 pending 包幂等复用。"""
    doc = get_document(conn, document_id)
    platform, title, body = doc["target_platform"], doc["title"], doc["content_md"]
    if variant_id:
        variant = get_variant(conn, variant_id)
        if variant["document_id"] != document_id:
            raise ValidationFailed("平台版本不属于该稿件", details={"variant_id": variant_id})
        platform, title, body = variant["platform"], variant["title"], variant["content_md"]
    if not (body or "").strip():
        raise ValidationFailed("内容为空，先写正文或生成平台版本再移交发布")
    h1, body_rest = split_leading_h1(body)
    title = title or h1 or "未命名稿件"
    digest = hashlib.sha1(f"{title}\n{body}".encode()).hexdigest()[:12]
    for pkg in list_packages():
        existing = pkg["handoff"]
        if (
            existing.get("status") == "pending"
            and existing.get("document_id") == document_id
            and existing.get("variant_id") == variant_id
            and existing.get("content_hash") == digest
        ):
            return pkg
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")[:40] or "document"
    base = f"{stamp}-{platform}-{slug}"
    root = _ensure_outbox_dir()
    pkg_dir, n = root / base, 1
    while pkg_dir.exists():
        n += 1
        pkg_dir = root / f"{base}-{n}"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "content.md").write_text(f"# {title}\n\n{body_rest}", encoding="utf-8")
    (pkg_dir / "content.txt").write_text(f"{title}\n\n{markdown_to_plain(body_rest)}", encoding="utf-8")
    if platform == "wechat":
        (pkg_dir / "wechat.html").write_text(markdown_to_wechat_html(body_rest), encoding="utf-8")
    manifest = {
        "protocol": PROTOCOL,
        "package": pkg_dir.name,
        "status": "pending",
        "platform": platform,
        "platform_name": PLATFORM_NAMES.get(platform, platform),
        "easel_publisher": EASEL_PUBLISHERS.get(platform),
        "title": title,
        "document_id": document_id,
        "variant_id": variant_id,
        "content_hash": digest,
        "created_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    (pkg_dir / HANDOFF_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"package": pkg_dir.name, "path": str(pkg_dir), "handoff": manifest, "result": None}


def sync_results(conn: sqlite3.Connection) -> dict:
    """把带 result.json 且发布成功的 pending 包记入发布账本；幂等。"""
    recorded: list[dict] = []
    skipped = 0
    warnings: list[str] = []
    for pkg in list_packages():
        manifest, result = pkg["handoff"], pkg["result"]
        if not result or manifest.get("status") != "pending":
            continue
        if str(result.get("status", "")).lower() not in _OK_STATUSES:
            skipped += 1
            continue
        url = (result.get("external_url") or result.get("url") or "").strip() or None
        note = (result.get("note") or "").strip() or f"Easel 桥接发布 · {pkg['package']}"
        try:
            publication = record_publication(
                conn,
                manifest["document_id"],
                platform=manifest["platform"],
                external_url=url,
                note=note,
                variant_id=manifest.get("variant_id"),
            )
        except (NotFound, ValidationFailed) as exc:
            skipped += 1
            warnings.append(f"{pkg['package']}: {exc}")
            continue
        manifest["status"] = "recorded"
        manifest["publication_id"] = publication["id"]
        manifest["recorded_at"] = datetime.now(tz=UTC).isoformat(timespec="seconds")
        (Path(pkg["path"]) / HANDOFF_FILE).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        recorded.append({"package": pkg["package"], "publication_id": publication["id"], "external_url": url})
    return {
        "recorded": recorded,
        "recorded_count": len(recorded),
        "skipped": skipped,
        "warnings": warnings,
    }


def easel_cli() -> str | None:
    """``easel`` 可执行文件路径；没装则 None。"""
    return shutil.which("easel")


def bridge_status() -> dict:
    packages = list_packages()
    by_status: dict[str, int] = {}
    for pkg in packages:
        status = str(pkg["handoff"].get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
    cli = easel_cli()
    return {
        "protocol": PROTOCOL,
        "outbox": str(outbox_dir()),
        "packages": len(packages),
        "by_status": by_status,
        # openclaw 装了 **不等于** Easel 装了：Easel 用独立的 profile（~/.openclaw-easel）
        # 和自己哈希出来的 gateway 端口。这两个字段分开报，免得把「桥接能出包」
        # 误读成「发布能跑通」。出包本身不依赖 Easel 是否安装。
        "openclaw_detected": (Path.home() / ".openclaw").exists(),
        "easel_detected": bool(cli) or (Path.home() / ".openclaw-easel").exists(),
        "easel_cli": cli,
        "easel_publishers": EASEL_PUBLISHERS,
    }
