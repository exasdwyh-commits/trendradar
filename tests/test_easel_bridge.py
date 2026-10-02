"""Easel 发布桥接与知识卡导出：handoff 包、result 回写入账（幂等）、card 格式."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from trendradar.core.errors import ValidationFailed


@pytest.fixture()
def outbox(tmp_path, monkeypatch) -> Path:
    from trendradar.core.settings import reset_settings

    path = tmp_path / "outbox"
    monkeypatch.setenv("EASEL_OUTBOX", str(path))
    reset_settings()
    yield path
    reset_settings()


def _make_doc(conn: sqlite3.Connection, content: str | None = None) -> str:
    from trendradar.studio.documents import create_document

    body = (
        content
        if content is not None
        else ("## 核心判断\n\n- 模型成本在快速下降\n- 分发渠道反而在变贵\n\n正文段落，解释判断依据。")
    )
    return create_document(conn, title="测试稿", content_md=body, target_platform="wechat", status="ready")


def test_handoff_creates_package_and_is_idempotent(conn, outbox):
    from trendradar.studio import easel_bridge as easel

    doc_id = _make_doc(conn)
    pkg = easel.handoff(conn, doc_id)
    pkg_dir = Path(pkg["path"])
    assert pkg_dir.parent == outbox
    assert (pkg_dir / "handoff.json").is_file()
    assert (pkg_dir / "content.md").is_file() and (pkg_dir / "content.txt").is_file()
    assert (pkg_dir / "wechat.html").is_file()  # wechat 平台附排版 HTML
    manifest = json.loads((pkg_dir / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["protocol"] == "trendradar-easel-handoff/1"
    assert manifest["status"] == "pending" and manifest["platform"] == "wechat"
    assert manifest["easel_publisher"] == "skill-wechat-publisher"
    # 同稿件同内容重复 handoff：复用 pending 包，不重复出包
    again = easel.handoff(conn, doc_id)
    assert again["package"] == pkg["package"]
    assert len(easel.list_packages()) == 1


def test_handoff_rejects_empty_document(conn, outbox):
    from trendradar.studio import easel_bridge as easel

    doc_id = _make_doc(conn, content="")
    with pytest.raises(ValidationFailed):
        easel.handoff(conn, doc_id)


def test_sync_records_published_result_once(conn, outbox):
    from trendradar.studio import easel_bridge as easel

    doc_id = _make_doc(conn)
    pkg = easel.handoff(conn, doc_id)
    (Path(pkg["path"]) / "result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "external_url": "https://mp.weixin.qq.com/s/demo",
                "note": "Easel 自动发布",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = easel.sync_results(conn)
    assert out["recorded_count"] == 1 and not out["warnings"]
    row = conn.execute("SELECT platform, external_url, note FROM publications").fetchone()
    assert row["platform"] == "wechat"
    assert row["external_url"] == "https://mp.weixin.qq.com/s/demo"
    # 幂等：重复 sync 不重复入账；稿件状态进入 published
    assert easel.sync_results(conn)["recorded_count"] == 0
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 1
    status = conn.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()[0]
    assert status == "published"
    manifest = json.loads((Path(pkg["path"]) / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "recorded" and manifest["publication_id"]


def test_sync_skips_failed_and_invalid_results(conn, outbox):
    from trendradar.studio import easel_bridge as easel

    doc_id = _make_doc(conn)
    pkg = easel.handoff(conn, doc_id)
    (Path(pkg["path"]) / "result.json").write_text(
        json.dumps({"status": "failed", "error": "平台风控"}), encoding="utf-8"
    )
    out = easel.sync_results(conn)
    assert out["recorded_count"] == 0 and out["skipped"] == 1
    assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0


def test_bridge_status_counts(conn, outbox):
    from trendradar.studio import easel_bridge as easel

    status = easel.bridge_status()
    assert status["packages"] == 0 and status["outbox"] == str(outbox)
    # openclaw 与 easel 分开报：装了 OpenClaw 不等于装了 Easel，不能混为一谈
    assert status["openclaw_detected"] is bool(Path.home().joinpath(".openclaw").exists())
    assert isinstance(status["easel_detected"], bool)
    easel.handoff(conn, _make_doc(conn))
    status = easel.bridge_status()
    assert status["packages"] == 1 and status["by_status"] == {"pending": 1}


def test_status_does_not_create_outbox(conn, outbox):
    """读接口不该有副作用：outbox 还没建时，查状态不能把它创建出来。"""
    from trendradar.studio import easel_bridge as easel

    assert not outbox.exists(), "fixture 不该预建 outbox"
    status = easel.bridge_status()
    assert status["packages"] == 0 and status["by_status"] == {}
    assert not outbox.exists(), "bridge_status() 是只读接口，不应创建 outbox 目录"
    # 只有真正出包才落盘
    easel.handoff(conn, _make_doc(conn))
    assert outbox.is_dir()


def test_card_export_is_self_contained(conn):
    from trendradar.studio.publishing import export_document

    doc_id = _make_doc(conn)
    content, media_type, filename = export_document(conn, doc_id, "card")
    assert media_type.startswith("text/html") and filename.endswith("_card.html")
    assert "测试稿" in content and "模型成本在快速下降" in content
    assert "1080px" in content and "1440px" in content  # 3:4 小红书画幅
    # 自包含：无脚本、无外链资源
    assert "<script" not in content and "<link" not in content and "src=" not in content


def test_card_points_fall_back_to_sentences():
    from trendradar.studio.cards import extract_points

    points = extract_points("- 第一条要点\n- 第二条要点\n- 短")
    assert points == ["第一条要点", "第二条要点"]
    prose = "没有列表的正文第一句，信息量足够。第二句话也有足够的长度。短句。"
    fallback = extract_points(prose)
    assert len(fallback) == 2 and fallback[0].startswith("没有列表")


#: Easel 仓库 skills/openclaw/ 下真实存在的 publisher 技能（frontmatter ``name``，
#: 2026-10-01 对 main 分支核对）。Easel 侧改名时这条会红，提醒同步 —— 名字写错
#: 不会报错，只会让 Agent 找不到技能、静默发不出去。
_REAL_EASEL_PUBLISHERS = {
    "skill-wechat-publisher",
    "skill-xhs-publisher",
    "skill-zhihu-publisher",
    "skill-douyin-upload",
    "skill-bilibili-upload",
    "skill-kuaishou-upload",
    "skill-channels-upload",
    "skill-cross-platform-publish",
}


def test_easel_publishers_are_real_easel_skills():
    from trendradar.studio import easel_bridge as easel

    assert easel.EASEL_PUBLISHERS, "映射不能为空"
    for platform, skill in easel.EASEL_PUBLISHERS.items():
        assert skill in _REAL_EASEL_PUBLISHERS, f"{platform} → {skill} 不是 Easel 的真实技能名"
        assert skill.startswith("skill-"), f"{skill} 应写 Easel 规范全名（带 skill- 前缀）"
