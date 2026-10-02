# Easel 发布桥接

TrendRadar 自身坚持**不直连平台 API**（见 README「范围之外」）。真实发布交给
[ZJU-REAL/Easel](https://github.com/ZJU-REAL/Easel)——它的 publisher 技能支持小红书 /
抖音 / 快手 / 知乎 / B站 / 微信视频号 / 微信公众号的登录与发布。桥接协议是
**纯文件握手**：不依赖 Easel 是否安装，不引入新服务，Easel 不可用时一切照旧。

```
TrendRadar 平台版本 ──handoff──► <outbox>/<package>/     ──Easel 读取并发布──┐
                                   handoff.json                             │
                                   content.md / content.txt / wechat.html   │
发布账本 ◄──sync（幂等入账）──     result.json  ◄──Easel 写回发布结果 ────────┘
```

## Handoff 包（`trendradar-easel-handoff/1`）

| 文件 | 内容 |
|---|---|
| `handoff.json` | 平台、标题、`document_id` / `variant_id`、内容哈希、状态（`pending` → `recorded`） |
| `content.md` | 正文 Markdown（首行 H1 为标题） |
| `content.txt` | 纯文本（小红书 / X 等短内容平台直接可用） |
| `wechat.html` | 仅公众号：内联样式排版 HTML，粘贴进公众号编辑器即用 |

发布完成后，发布方（Easel Agent、其他自动化、或人工）在包目录写 `result.json`：

```json
{"status": "published", "external_url": "https://mp.weixin.qq.com/s/…", "note": "可选备注"}
```

`status` 取 `published` / `success` / `ok` 之一才会入账；其他值（如 `failed`）会被
sync 跳过并保留在 outbox 里供排查。

## API

| 端点 | 作用 |
|---|---|
| `GET /api/publish/easel` | 桥接状态：outbox 路径、包计数、OpenClaw 检测、支持的 publisher |
| `POST /api/documents/{id}/easel-handoff` | 导出 handoff 包（body 可带 `variant_id`）；同内容幂等复用 |
| `POST /api/publish/easel/sync` | 扫描 result.json，入发布账本（幂等），稿件状态置 `published` |

## 平台 → Easel 技能

`handoff.json` 的 `easel_publisher` 字段是 Easel 的**技能规范全名**，由
`studio/easel_bridge.py` 的 `EASEL_PUBLISHERS` 决定（2026-10-01 对 Easel main 分支核对）：

| TrendRadar 平台 | `easel_publisher` | 说明 |
|---|---|---|
| `wechat` | `skill-wechat-publisher` | 该技能自带调研与成文，**喂成品时要在指令里明确「内容已定稿，只发布到草稿箱，不要重写」** |
| `xiaohongshu` | `skill-xhs-publisher` | 纯发布（Playwright + 持久登录态），直接吃 `content.txt` |
| `zhihu` | `skill-zhihu-publisher` | 纯发布，发到知乎专栏 |
| `toutiao` / `x` | `null` | Easel 无对应 publisher，包照常出，人工或其他自动化处理 |

Easel CLI 解析技能名的规则是「先按字面找，找不到再加 `skill-` 前缀」（`easel/commands/skill.py`），
所以两种写法都能命中；本仓库统一写全名。**技能名写错不会报错**，只会让 Agent 找不到技能、
静默发不出去 —— `tests/test_easel_bridge.py::test_easel_publishers_are_real_easel_skills` 守住这条。

## 配置

`.env`（见 `.env.example`）中设置 `EASEL_OUTBOX` 可把 outbox 指到 Easel 的工作目录（默认
`<data_dir>/easel_outbox`；留空即用默认位置）。给 Easel Agent 的提示词示例：

> 监视 `<outbox>` 目录：出现 `handoff.json` 状态为 pending 的包时，按其 `platform`
> 用对应 publisher 技能发布 `content.md`（公众号用 `wechat.html`），完成后在包目录
> 写 `result.json`（status / external_url / note），不要修改 handoff.json。

## 注意

- **「能出包」不等于「能发布」**：`GET /api/publish/easel` 分别报 `openclaw_detected` 与
  `easel_detected`。装了 OpenClaw 只是满足前置条件 —— Easel 用独立 profile
  （`~/.openclaw-easel`）和自己哈希出来的 gateway 端口，两者要分开看。出包本身不依赖 Easel。
- **小红书**：Easel 官方提示自动发布存在风控风险，建议预览 + 人工确认后再发；
  手动发布后同样可以自己写 `result.json`，让账本保持完整。
- `toutiao` / `x` 平台 Easel 暂无 publisher，handoff 包照常生成（`easel_publisher: null`），
  由人工或其他自动化处理。
- 知识卡：`GET /api/documents/{id}/export?fmt=card` 导出 3:4 自包含 HTML 卡片
  （小红书画幅，无外链资源），浏览器打开截图即可用作首图。
